# -*- coding: utf-8 -*-
"""
썬더미리 — 발송 엔진
GitHub Actions에서 5분마다 실행(cron-job.org가 트리거). 동작 순서:
  1) Supabase에서 구독자(동네·격자·웹푸시토큰) 읽기
  2) 같은 격자끼리 묶어 기상청 낙뢰 관측 정보 조회 (API 절약)
  3) 천둥 감지된 격자의 구독자에게 웹푸시 발송
  4) 최초 관측과 거리 단계 변화가 있을 때만 알림 발송

기상청 조회 로직은 '동탄이 봇'(lightning_alert.py)에서 가져와 위치를 매개변수화함.
"""
import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from pywebpush import webpush, WebPushException


KST = timezone(timedelta(hours=9))


# ==========================================
# 설정 (클라우드에선 환경변수/Secrets, 로컬 테스트는 .env.secret 로드)
# ==========================================
# .strip(): Secrets에 값 붙여넣을 때 끝에 줄바꿈/공백이 들어가도 안전하게
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pdlohzenslwbiyoxwjom.supabase.co").strip()
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "").strip()  # sb_secret_... (RLS 우회, 절대 공개 금지)
KMA_API_KEY = os.environ.get("KMA_API_KEY", "").strip()

VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:kustomduo@gmail.com").strip()

# 관리자 경보용 텔레그램(동탄이 봇 재사용). 사용자에게 가는 알림과는 무관하며,
# 발송이 조용히 멈추는 상황을 운영자가 알기 위한 채널이다.
# 값이 없으면 경보만 건너뛰고 발송은 정상 진행한다.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
# 이 시간 넘게 성공 기록이 없으면 "그동안 발송이 멈춰 있었다"고 판단한다(정상 주기 5분).
STALE_MINUTES = int(os.environ.get("STALE_MINUTES", "15"))
# 기상청 조회가 연속 몇 회 실패하면 경보를 보낼지. 순간적인 끊김으로 경보가
# 남발되면 정작 진짜 장애 때 무시하게 된다.
FAIL_ALERT_STREAK = int(os.environ.get("FAIL_ALERT_STREAK", "2"))

WARNING_RADIUS_KM = float(os.environ.get("WARNING_RADIUS_KM", "30"))  # 30km 이내: 임박
WATCH_RADIUS_KM = float(os.environ.get("WATCH_RADIUS_KM", "50"))      # 50km 이내: 접근
# 반경 안에 낙뢰가 몇 건 이상이어야 "뇌우가 왔다"고 볼지.
# 1로 두면 뇌우와 무관한 외딴 한 발에도 알림이 나간다(2026-08-21 오경보).
# 진짜 뇌우는 한 주기에 수십~수백 건이라 3으로 올려도 지연은 거의 없다.
MIN_STRIKES = int(os.environ.get("MIN_STRIKES", "3"))

# HTTP 연결 재사용 세션.
# 매 요청마다 TLS 손잡이를 새로 하면 느리다(실측: 푸시 330ms→146ms, Supabase 170ms→42ms).
# 발송은 구독자 수만큼 반복되므로 사람이 늘수록 차이가 커진다.
PUSH_SESSION = requests.Session()   # FCM/Apple 푸시 서버용
SB_SESSION = requests.Session()     # Supabase REST용
KMA_SESSION = requests.Session()    # 기상청 API용 (주기당 1회)

# 전국 낙뢰를 한 번에 받는 조회 조건.
# 예전에는 격자마다 따로 조회해서 가입자가 흩어질수록 호출이 늘었다
# (격자 300곳 = 하루 86,400건 → 기상청 일반회원 한도 20,000건의 4배).
# 반경을 넓혀도 요청은 1회이고 응답도 가볍다 —
# 실측(2026-08-16): 500km·낙뢰 24건 = 1.6KB·100ms, 2000km로 넓혀도 결과 동일.
NATIONAL_LAT = float(os.environ.get("NATIONAL_LAT", "36.5"))
NATIONAL_LON = float(os.environ.get("NATIONAL_LON", "127.8"))
NATIONAL_RANGE_KM = float(os.environ.get("NATIONAL_RANGE_KM", "500"))
LOOKBACK_MINUTES = int(os.environ.get("LOOKBACK_MINUTES", "15"))
# 거리를 넓게 잡은 이유: 이 서비스의 목적이 '무방비 노출 방지'라 준비 시간이 길수록 좋다.
# 뇌우 이동속도 20~60km/h 기준 50km면 약 50분~2.5시간, 30km면 약 30분~1.5시간의 여유.
THUNDER_SOUND_URL = os.environ.get("THUNDER_SOUND_URL", "https://youtu.be/lpi6gd1H0Ok")
# 알림을 탭하면 열리는 화면. 보호자가 실제로 하는 행동(레이더로 상황 확인)에 맞춤.
ALERT_CLICK_URL = os.environ.get("ALERT_CLICK_URL", "https://thundermiri.com/#radar")

# ----------------------------------------------------------------
# 로컬 테스트용 .env.secret 읽기 (KEY=VALUE 한 줄씩). 클라우드에선 파일 없으니 무시됨.
# ----------------------------------------------------------------
def load_local_env():
    path = os.path.join(os.path.dirname(__file__), ".env.secret")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


# ----------------------------------------------------------------
# 관리자 경보 (텔레그램)
# ----------------------------------------------------------------
def notify_admin(message):
    """운영자에게만 보내는 경보. 실패해도 발송 본체를 막지 않는다."""
    if not (TELEGRAM_TOKEN and TELEGRAM_CHAT_ID):
        print(f"[경보-미설정] {message}")
        return False
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": f"[썬더미리] {message}"},
            timeout=15,
        )
        res.raise_for_status()
        print(f"[경보 발송] {message}")
        return True
    except Exception as e:
        print(f"[경보 실패] {e} / 원래 메시지: {message}")
        return False


# ----------------------------------------------------------------
# 공통 HTTP (일시적 지연 대비 재시도)
# ----------------------------------------------------------------
def http_get(url, params, tries=3, timeout=30):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            res = KMA_SESSION.get(url, params=params, timeout=timeout)
            res.raise_for_status()
            return res
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < tries:
                time.sleep(2)
    raise last_err


def haversine(lat1, lon1, lat2, lon2):
    """두 위경도 간 거리(km)"""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ----------------------------------------------------------------
# 기상청 조회 (동탄이 봇에서 재활용, 위치 매개변수화)
# ----------------------------------------------------------------
def fetch_lightning_data(lat, lon, range_km, lookback_minutes=15, strict=False):
    """기상청 API허브 최근 낙뢰 좌표 목록.

    strict=False면 실패해도 빈 목록을 돌려준다(레이더 생성용 — 그림이 한 주기
    낡을 뿐이라 치명적이지 않다).
    strict=True면 예외를 그대로 올린다. 발송 경로에서는 '조회 실패'와
    '낙뢰 없음'을 반드시 구분해야 하기 때문이다 — 둘을 섞으면 기상청이 죽은
    날에도 워크플로우는 초록불이고 천둥이 쳐도 알림이 안 간다.
    """
    # ⚠️ itv가 60 이상이면 기상청이 '최근' 자료를 주지 않는다 (2026-08-21 실측).
    #    itv<60  → [지금-itv, 지금]        정상
    #    itv=60  → 데이터 0건
    #    itv>60  → [지금-itv, 지금-65]     최근 65분이 통째로 빠짐
    #    호출부가 실수로 60을 넣어도 화면이 비지 않도록 여기서 막는다.
    if lookback_minutes >= 60:
        print(f"[낙뢰 조회] itv={lookback_minutes}는 최근 자료가 안 옵니다. 59로 낮춥니다.")
        lookback_minutes = 59

    url = "https://apihub.kma.go.kr/api/typ01/url/lgt_pnt.php"
    params = {
        "tm": datetime.now(KST).strftime("%Y%m%d%H%M"),
        "itv": lookback_minutes, "lon": lon, "lat": lat, "range": range_km,
        "gc": "T", "authKey": KMA_API_KEY,
    }
    try:
        res = http_get(url, params)
        if not res.encoding:
            res.encoding = "euc-kr"
        items = []
        for line in res.text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.upper().startswith("TM"):
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 5:
                continue
            items.append({"tm": parts[0], "lon": parts[1], "lat": parts[2], "st": parts[3], "type": parts[4]})
        return items
    except Exception as e:
        print(f"[낙뢰 조회 실패] {e}")
        if strict:
            raise
        return []


def fetch_lightning_nationwide():
    """한반도 전역의 최근 낙뢰를 한 번에 가져온다. 가입자가 몇 명이든 주기당 1회."""
    return fetch_lightning_data(NATIONAL_LAT, NATIONAL_LON, NATIONAL_RANGE_KM,
                                lookback_minutes=LOOKBACK_MINUTES, strict=True)


def parse_strikes(items):
    """조회 결과를 (위도, 경도) 숫자 목록으로. 좌표가 깨진 건은 버린다."""
    strikes = []
    for it in items:
        try:
            strikes.append((float(it["lat"]), float(it["lon"])))
        except (TypeError, ValueError):
            continue
    return strikes


# 사각형으로 먼저 걸러 haversine 호출을 줄인다. 경도 1도는 위도 36°에서 약 90km라
# 반경/80 이면 두 축 모두 안전하게 감싼다(걸러낸 뒤 실제 거리로 다시 판정하므로 오차 없음).
NEAR_DEG = WATCH_RADIUS_KM / 80.0


def nearest_strike_km(lat, lon, strikes):
    """이 좌표에서 가장 가까운 낙뢰까지 거리(km). 관측 범위 안에 없으면 None."""
    nearest, _, _ = strike_summary(lat, lon, strikes)
    return nearest


def strike_summary(lat, lon, strikes):
    """(최근접 거리, 50km 이내 개수, 30km 이내 개수)를 한 번에 센다.

    개수가 필요한 이유: 뇌우와 멀리 떨어진 곳에 한 발만 튀는 낙뢰가 실제로 있다.
    2026-08-21에 서해 뇌우(197건)와 무관하게 내륙에 딱 1건이 찍혀
    45km 알림이 나갔는데, 다가오는 뇌우가 아니라 준비할 것이 없는 상황이었다.
    """
    nearest = None
    watch_n = warn_n = 0
    for s_lat, s_lon in strikes:
        if abs(s_lat - lat) > NEAR_DEG or abs(s_lon - lon) > NEAR_DEG:
            continue
        d = haversine(lat, lon, s_lat, s_lon)
        if d <= WATCH_RADIUS_KM:
            watch_n += 1
            if d <= WARNING_RADIUS_KM:
                warn_n += 1
        if nearest is None or d < nearest:
            nearest = d
    return nearest, watch_n, warn_n


# ----------------------------------------------------------------
# 심장박동 — "돌긴 돌았는가"를 기록한다
#
# 워크플로우가 아예 실행되지 않으면(cron-job.org 중단, Actions 장애) 실패 기록조차
# 남지 않아 눈치채기 어렵다. 성공할 때마다 시각을 남겨두면, 다음에 살아난 실행이
# "그동안 몇 번 걸렀는지"를 역산해 알릴 수 있다.
# 기존 radar 버킷에 파일 하나로 두어 DB 스키마 변경이 필요 없다.
# ----------------------------------------------------------------
HEARTBEAT_FILE = "heartbeat.json"


def _heartbeat_url(public=False):
    kind = "object/public" if public else "object"
    return f"{SUPABASE_URL}/storage/v1/{kind}/radar/{HEARTBEAT_FILE}"


def read_heartbeat():
    # 공개 URL은 CDN 캐시 때문에 방금 쓴 값이 바로 안 보인다(?cb=로도 확실하지 않음).
    # 연속 실패 횟수를 세려면 직전에 쓴 값을 정확히 읽어야 하므로 인증 경로로 읽는다.
    try:
        res = SB_SESSION.get(_heartbeat_url(), headers=sb_headers(), timeout=15)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"[심장박동 읽기 실패] {e}")
    return None


def _put_heartbeat(data):
    body = json.dumps(data, ensure_ascii=False).encode()
    headers = sb_headers()
    headers["x-upsert"] = "true"
    try:
        res = SB_SESSION.post(_heartbeat_url(), headers=headers, data=body, timeout=20)
        if res.status_code >= 400:
            print(f"[심장박동 기록 실패] {res.status_code} {res.text[:120]}")
    except Exception as e:
        print(f"[심장박동 기록 실패] {e}")


def write_heartbeat(sent_count, strike_count):
    _put_heartbeat({
        "last_success": datetime.now(KST).isoformat(timespec="seconds"),
        "sent": sent_count,
        "strikes": strike_count,
        "fail_streak": 0,          # 성공했으니 연속 실패 기록을 지운다
    })


def record_failure(reason):
    """조회 실패를 기록하고, 연속 몇 번째인지 돌려준다.

    기상청은 정각 부하 등으로 가끔 순간적으로 끊긴다. 한 번 튈 때마다 경보를
    보내면 금세 무시하게 되므로(경보 시스템이 죽는 가장 흔한 이유), 몇 번째
    연속 실패인지를 남겨 호출부가 판단하게 한다.
    last_success는 건드리지 않는다 — 공백 감지의 기준이기 때문이다.
    """
    hb = read_heartbeat() or {}
    streak = int(hb.get("fail_streak", 0)) + 1
    hb.update({
        "fail_streak": streak,
        "last_fail": datetime.now(KST).isoformat(timespec="seconds"),
        "last_fail_reason": str(reason)[:200],
    })
    _put_heartbeat(hb)
    return streak


def check_missed_runs():
    """직전 성공 이후 얼마나 비었는지 확인하고, 오래 비었으면 경보를 보낸다."""
    hb = read_heartbeat()
    if not hb or not hb.get("last_success"):
        return
    try:
        last = datetime.fromisoformat(hb["last_success"])
    except ValueError:
        return
    gap_min = (datetime.now(KST) - last).total_seconds() / 60
    if gap_min >= STALE_MINUTES:
        missed = int(gap_min // 5) - 1     # 정상 주기 5분 기준
        notify_admin(
            f"발송이 {gap_min:.0f}분간 멈춰 있었습니다 (약 {missed}회 거름).\n"
            f"마지막 성공: {hb['last_success']}\n"
            f"지금은 복구되어 정상 실행 중입니다."
        )


# ----------------------------------------------------------------
# Supabase (secret 키로 RLS 우회해 전체 읽기/수정)
# ----------------------------------------------------------------
def sb_headers():
    return {
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def get_subscribers():
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    params = {
        "select": "id,created_at,lat,lon,nx,ny,dong,subscription,last_lightning_at,last_lightning_level",
        "active": "eq.true",
        "order": "created_at.asc",   # 오래된 가입자 우선 (격자 상한에 걸릴 때 먼저 지킨다)
    }
    res = SB_SESSION.get(url, headers=sb_headers(), params=params, timeout=30)
    res.raise_for_status()
    # 웹푸시 토큰 있는 사람만
    return [s for s in res.json() if s.get("subscription")]


def cap_grids(grids, limit, label):
    """격자 수 상한. 급증(스팸·공격)해도 서비스가 통째로 멈추지 않게 한다.

    발송(sender)은 전국을 1회만 조회하도록 바뀌어 이 상한이 필요 없어졌고,
    지금은 레이더 생성(radar.py)만 쓴다 — 격자 하나마다 기상청 호출 ~10회와
    이미지 업로드 12개가 발생해 여전히 격자 수 = 비용이기 때문이다.
    자를 때는 가입이 오래된 쪽을 남긴다(get_subscribers가 created_at 오름차순으로 주므로
    dict 삽입 순서가 곧 가입 순서 — 뒤에 밀어 넣은 행이 먼저 잘린다).
    """
    if len(grids) <= limit:
        return grids
    dropped = len(grids) - limit
    print(f"[경고] {label} 격자 {len(grids)}곳 — 상한 {limit} 초과. "
          f"오래된 순으로 {limit}곳만 처리하고 {dropped}곳 건너뜀.")
    print(f"[경고] 정상 증가인지 스팸 가입인지 subscribers 테이블을 확인할 것.")
    return dict(list(grids.items())[:limit])


PATCH_CHUNK = 200   # 한 번의 PATCH에 담을 최대 인원 (URL 길이 한계 고려)


def _patch_many(ids, body, label):
    """여러 명을 한 번의 PATCH로 갱신한다.

    한 명씩 보내면 1명당 왕복 170ms가 붙어 인원수만큼 느려진다.
    (1000명이면 그것만 170초) 같은 값으로 바뀌는 사람끼리 묶어 한 번에 보낸다.
    """
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    for i in range(0, len(ids), PATCH_CHUNK):
        chunk = ids[i:i + PATCH_CHUNK]
        try:
            res = SB_SESSION.patch(url, headers=sb_headers(),
                                   params={"id": f"in.({','.join(chunk)})"},
                                   json=body, timeout=30)
            if not res.ok:
                print(f"[{label} 실패] {res.status_code} {res.text[:150]}")
        except Exception as e:
            print(f"[{label} 실패] {e}")


def mark_lightning_bulk(pairs):
    """[(구독자id, 단계), ...] → 단계별로 묶어 일괄 갱신"""
    if not pairs:
        return
    by_level = {}
    for sub_id, level in pairs:
        by_level.setdefault(level, []).append(sub_id)
    now = datetime.now(timezone.utc).isoformat()
    for level, ids in by_level.items():
        _patch_many(ids, {"last_lightning_at": now, "last_lightning_level": level},
                    "last_lightning 갱신")


def reset_lightning_bulk(ids):
    """낙뢰가 사라진 사람들의 단계 리셋 → 다음 천둥 때 다시 즉시 알림"""
    if not ids:
        return
    _patch_many(ids, {"last_lightning_level": None}, "last_lightning 리셋")


def deactivate(sub_id):
    """만료된(410/404) 구독은 비활성화"""
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    try:
        SB_SESSION.patch(url, headers=sb_headers(), params={"id": f"eq.{sub_id}"},
                         json={"active": False}, timeout=15)
        print(f"  → 만료 구독 비활성화 ({sub_id})")
    except Exception as e:
        print(f"[비활성화 실패] {e}")


def lightning_transition(prev_level, cur_level):
    """최초 관측과 의미 있는 거리 단계 변화만 알림 유형으로 변환한다."""
    if prev_level not in ("watch", "warning"):
        return "initial_warning" if cur_level == "warning" else "initial_watch"
    if prev_level == "watch" and cur_level == "warning":
        return "closer"
    if prev_level == "warning" and cur_level == "watch":
        return "farther"
    return None


# ----------------------------------------------------------------
# 웹푸시 발송
# ----------------------------------------------------------------
def send_web_push(subscription, title, body, url=ALERT_CLICK_URL):
    payload = json.dumps({"title": title, "body": body, "url": url}, ensure_ascii=False)
    try:
        webpush(
            subscription_info=subscription,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
            requests_session=PUSH_SESSION,   # 연결 재사용 (한 명씩 순차라 누적 효과가 큼)
        )
        return True, None
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        print(f"[푸시 실패] status={status} {e}")
        return False, status


# ----------------------------------------------------------------
# 메시지 문구
# ----------------------------------------------------------------
def build_message(alert_type, dist=None):
    """거리 기반 낙뢰 관측 사실과 단계 변화만 전달한다."""
    km = round(dist) if dist is not None else None
    if alert_type == "initial_watch":
        return ("⚡ 썬더미리 · 50km 이내 낙뢰 관측",
                f"등록한 위치에서 약 {km}km 떨어진 곳에 낙뢰가 관측됐어요. 썬더미리에서 최근 낙뢰 위치를 확인해 주세요.")
    if alert_type == "initial_warning":
        return ("🚨 썬더미리 · 30km 이내 낙뢰 관측",
                f"등록한 위치에서 약 {km}km 떨어진 곳에 낙뢰가 관측됐어요. 썬더미리에서 낙뢰 레이더를 확인해 주세요.")
    if alert_type == "closer":
        return ("🚨 낙뢰 관측 지점이 가까워졌어요",
                "가장 가까운 최근 낙뢰가 등록한 위치 30km 이내에서 관측됐어요. 썬더미리에서 낙뢰 레이더를 확인해 주세요.")
    if alert_type == "farther":
        return ("↗️ 가장 가까운 낙뢰가 멀어졌어요",
                "가장 가까운 최근 낙뢰가 등록한 위치 30km 밖에서 관측됐어요. 썬더미리에서 주변 낙뢰 상황을 확인해 주세요.")
    raise ValueError(f"지원하지 않는 알림 유형: {alert_type}")


# ----------------------------------------------------------------
# 한 번 확인 (클라우드에서 5분마다 호출)
# ----------------------------------------------------------------
def run_once():
    # 지난 주기들이 통째로 비어 있었는지 먼저 확인한다(복구 시점에 알리기 위함)
    check_missed_runs()

    subs = get_subscribers()
    if not subs:
        print(f"[{datetime.now():%H:%M:%S}] 구독자 없음(또는 푸시토큰 없음). 종료.")
        return

    # 전국 낙뢰를 한 번만 받아온다. 이후 거리 계산은 각자의 좌표로 우리가 직접 한다.
    # (격자로 묶어 조회하던 방식은 가입자가 흩어질수록 기상청 호출이 늘어 한도에 걸렸다)
    try:
        strikes = parse_strikes(fetch_lightning_nationwide())
    except Exception as e:
        # 여기서 조용히 빈 목록으로 넘어가면 '낙뢰 없음'과 구별되지 않는다.
        # 다만 기상청은 가끔 순간적으로 끊기므로, 한 번 튄 것까지 경보를 보내면
        # 곧 무시하게 된다. 연속 2회(=10분간 깜깜)부터 알리고 실패로 끝낸다.
        streak = record_failure(f"{type(e).__name__}: {e}")
        print(f"[낙뢰 조회 실패] 연속 {streak}회")
        if streak < FAIL_ALERT_STREAK:
            print(f"[경보 보류] {FAIL_ALERT_STREAK}회 연속부터 알립니다. 이번 주기는 건너뜁니다.")
            return
        notify_admin(f"⚠️ 기상청 낙뢰 조회가 연속 {streak}회 실패했습니다 "
                     f"(약 {streak * 5}분간 낙뢰를 확인하지 못함).\n"
                     f"{type(e).__name__}: {str(e)[:200]}")
        raise

    print(f"[{datetime.now():%H:%M:%S}] 구독자 {len(subs)}명 / 전국 낙뢰 {len(strikes)}건")

    # DB 갱신은 모아서 마지막에 한 번에 보낸다(1명당 왕복 170ms 제거).
    # 도중에 죽으면 갱신이 안 되어 다음 주기에 같은 알림이 한 번 더 갈 수 있다.
    # (알림이 빠지는 것보다 한 번 더 가는 쪽이 안전하므로 이 방향을 택함)
    pending_marks = []    # [(id, level)] 발송 성공 → 단계 기록
    pending_resets = []   # [id]          낙뢰 사라짐 → 단계 리셋

    try:
        _run_subscribers(subs, strikes, pending_marks, pending_resets)
    finally:
        mark_lightning_bulk(pending_marks)
        reset_lightning_bulk(pending_resets)
        if pending_marks or pending_resets:
            print(f"[DB] 단계기록 {len(pending_marks)}명 · 리셋 {len(pending_resets)}명 일괄 반영")

    # 여기까지 왔으면 이번 주기는 정상이다. 다음 실행이 공백을 판단할 근거를 남긴다.
    write_heartbeat(len(pending_marks), len(strikes))


def _run_subscribers(subs, strikes, pending_marks, pending_resets):
    """가입자 각자의 좌표로 낙뢰 거리를 재고 단계가 바뀐 사람에게만 발송한다.
    DB 갱신은 pending 목록에 모아만 둔다.

    격자 대표 좌표가 아니라 본인 좌표로 계산하므로 같은 동네라도 거리가 각각 나온다
    (예전 방식은 격자 5km 안을 전부 같은 거리로 취급해 최대 3~4km 오차가 있었다)."""
    sent = watching = 0
    for s in subs:
        try:
            lat, lon = float(s["lat"]), float(s["lon"])
        except (TypeError, ValueError):
            continue

        # 1) 낙뢰 거리 → 단계(none/watch/warning) — 예보가 아니라 '실측' 기반
        #    거리만 보지 않고 개수도 본다. 외딴 한 발은 뇌우 접근이 아니다.
        nearest, watch_n, warn_n = strike_summary(lat, lon, strikes)
        lightning_level = None
        if nearest is not None:
            if nearest <= WARNING_RADIUS_KM and warn_n >= MIN_STRIKES:
                lightning_level = "warning"   # 30km 이내: 임박
            elif nearest <= WATCH_RADIUS_KM and watch_n >= MIN_STRIKES:
                lightning_level = "watch"      # 50km 이내: 접근
            elif watch_n:
                print(f"  {s.get('dong') or ''}: {nearest:.0f}km에 낙뢰 {watch_n}건 "
                      f"— {MIN_STRIKES}건 미만이라 보류")

        if lightning_level is None:
            # 낙뢰가 사라졌으니 단계 리셋 → 다음 천둥 때 다시 즉시 알림
            if s.get("last_lightning_level"):
                pending_resets.append(s["id"])
            continue

        watching += 1
        # --- ⚡ 최초 관측 또는 50km/30km 거리 단계가 바뀔 때만 발송 ---
        transition = lightning_transition(s.get("last_lightning_level"), lightning_level)
        if not transition:
            continue

        title, body = build_message(transition, dist=nearest)
        ok, status = send_web_push(s["subscription"], title, body)
        if ok:
            pending_marks.append((s["id"], lightning_level))
            sent += 1
            print(f"  {s.get('dong') or s['id'][:8]}: {lightning_level} "
                  f"({nearest:.0f}km, {transition}) → 발송")
        elif status in (404, 410):
            deactivate(s["id"])

    print(f"[결과] 관측범위 안 {watching}명 / 발송 {sent}명")


# ----------------------------------------------------------------
# 테스트: 날씨 무관하게 모든 구독자에게 1회 푸시 (발송 연결 확인용)
# ----------------------------------------------------------------
def run_test():
    subs = get_subscribers()
    print(f"구독자 {len(subs)}명에게 테스트 푸시")
    for s in subs:
        ok, status = send_web_push(
            s["subscription"],
            "⚡ 썬더미리 테스트",
            "알림 연결이 정상입니다. 실제 낙뢰가 관측되면 등록한 위치를 기준으로 알려드립니다.",
        )
        print(f"  {s.get('dong') or s['id'][:8]}: {'성공' if ok else f'실패({status})'}")
        if status in (404, 410):
            deactivate(s["id"])


def validate_config(need_kma=True):
    required = {
        "SUPABASE_SECRET_KEY": SUPABASE_SECRET_KEY,
        "VAPID_PRIVATE_KEY": VAPID_PRIVATE_KEY,
    }
    if need_kma:  # 실제 천둥감지(--once)에만 기상청 키 필요. 테스트(--test)는 불필요.
        required["KMA_API_KEY"] = KMA_API_KEY
    missing = [k for k, v in required.items() if not v.strip()]
    if missing:
        print("필수 설정 누락:", ", ".join(missing))
        return False
    return True


if __name__ == "__main__":
    load_local_env()
    # load_local_env 후 전역값 다시 읽기
    SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", SUPABASE_SECRET_KEY).strip()
    KMA_API_KEY = os.environ.get("KMA_API_KEY", KMA_API_KEY).strip()
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", VAPID_PRIVATE_KEY).strip()

    parser = argparse.ArgumentParser(description="썬더미리 발송 엔진")
    parser.add_argument("--once", action="store_true", help="한 번 확인하고 종료(클라우드용)")
    parser.add_argument("--test", action="store_true", help="모든 구독자에게 테스트 푸시")
    args = parser.parse_args()

    if not validate_config(need_kma=not args.test):
        raise SystemExit(1)

    if args.test:
        run_test()
    else:
        run_once()
