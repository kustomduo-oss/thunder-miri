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

WARNING_RADIUS_KM = float(os.environ.get("WARNING_RADIUS_KM", "30"))  # 30km 이내: 임박
WATCH_RADIUS_KM = float(os.environ.get("WATCH_RADIUS_KM", "50"))      # 50km 이내: 접근

# 격자 수 상한 (스팸·공격 대비 안전장치). 격자 1곳 = 기상청 낙뢰 조회 1회.
# 발송은 서비스의 존재 이유라 넉넉하게 둔다. 레이더(radar.py)는 훨씬 무거워 따로 낮게 잡음.
MAX_GRIDS = int(os.environ.get("MAX_GRIDS", "300"))
# 거리를 넓게 잡은 이유: 이 서비스의 목적이 '무방비 노출 방지'라 준비 시간이 길수록 좋다.
# 뇌우 이동속도 20~60km/h 기준 50km면 약 50분~2.5시간, 30km면 약 30분~1.5시간의 여유.
THUNDER_SOUND_URL = os.environ.get("THUNDER_SOUND_URL", "https://youtu.be/lpi6gd1H0Ok")
# 알림을 탭하면 열리는 화면. 보호자가 실제로 하는 행동(레이더로 상황 확인)에 맞춤.
ALERT_CLICK_URL = os.environ.get("ALERT_CLICK_URL", "https://kustomduo-oss.github.io/thunder-miri/index.html#radar")

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
# 공통 HTTP (일시적 지연 대비 재시도)
# ----------------------------------------------------------------
def http_get(url, params, tries=3, timeout=30):
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            res = requests.get(url, params=params, timeout=timeout)
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
def fetch_lightning_data(lat, lon, range_km, lookback_minutes=15):
    """기상청 API허브 최근 낙뢰 좌표 목록"""
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
        return []


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
        "select": "id,created_at,dog_name,lat,lon,nx,ny,dong,subscription,last_lightning_at,last_lightning_level",
        "active": "eq.true",
        "order": "created_at.asc",   # 오래된 가입자 우선 (격자 상한에 걸릴 때 먼저 지킨다)
    }
    res = requests.get(url, headers=sb_headers(), params=params, timeout=30)
    res.raise_for_status()
    # 웹푸시 토큰 있는 사람만
    return [s for s in res.json() if s.get("subscription")]


def cap_grids(grids, limit, label):
    """격자 수 상한. 급증(스팸·공격)해도 서비스가 통째로 멈추지 않게 한다.

    격자 하나가 곧 기상청 API 호출이라 격자 수 = 비용이다.
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


def mark_lightning(sub_id, level):
    """낙뢰 경보 시각·단계 갱신"""
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    now = datetime.now(timezone.utc).isoformat()
    try:
        requests.patch(url, headers=sb_headers(), params={"id": f"eq.{sub_id}"},
                       json={"last_lightning_at": now, "last_lightning_level": level}, timeout=15)
    except Exception as e:
        print(f"[last_lightning 갱신 실패] {e}")


def reset_lightning(sub_id):
    """낙뢰가 사라지면 단계 리셋 → 다음 천둥 때 다시 즉시 알림"""
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    try:
        requests.patch(url, headers=sb_headers(), params={"id": f"eq.{sub_id}"},
                       json={"last_lightning_level": None}, timeout=15)
    except Exception as e:
        print(f"[last_lightning 리셋 실패] {e}")


def deactivate(sub_id):
    """만료된(410/404) 구독은 비활성화"""
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    try:
        requests.patch(url, headers=sb_headers(), params={"id": f"eq.{sub_id}"},
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
    subs = get_subscribers()
    if not subs:
        print(f"[{datetime.now():%H:%M:%S}] 구독자 없음(또는 푸시토큰 없음). 종료.")
        return

    # 같은 격자끼리 묶기 (대표 좌표 1개로 기상청 1번만 호출)
    grids = {}
    for s in subs:
        key = (s["nx"], s["ny"])
        g = grids.setdefault(key, {"lat": s["lat"], "lon": s["lon"], "dong": s.get("dong"), "subs": []})
        g["subs"].append(s)

    grids = cap_grids(grids, MAX_GRIDS, "발송")

    print(f"[{datetime.now():%H:%M:%S}] 구독자 {len(subs)}명 / 격자 {len(grids)}곳 확인")

    for (nx, ny), g in grids.items():
        # 1) 낙뢰 거리 → 단계(none/watch/warning) — 예보가 아니라 '실측' 기반
        nearest = None
        for it in fetch_lightning_data(g["lat"], g["lon"], WATCH_RADIUS_KM):
            try:
                d = haversine(g["lat"], g["lon"], float(it["lat"]), float(it["lon"]))
            except (TypeError, ValueError):
                continue
            if nearest is None or d < nearest:
                nearest = d
        lightning_level = None
        if nearest is not None:
            if nearest <= WARNING_RADIUS_KM:
                lightning_level = "warning"   # 30km 이내: 임박
            elif nearest <= WATCH_RADIUS_KM:
                lightning_level = "watch"      # 50km 이내: 접근

        if lightning_level is None:
            print(f"  격자({nx},{ny}) {g.get('dong') or ''}: 낙뢰 없음")
            # 낙뢰가 사라졌으니 단계 리셋 → 다음 천둥 때 다시 즉시 알림
            for s in g["subs"]:
                if s.get("last_lightning_level"):
                    reset_lightning(s["id"])
            continue

        print(f"  격자({nx},{ny}) {g.get('dong') or ''}: "
              f"낙뢰={lightning_level} → {len(g['subs'])}명 처리")

        for s in g["subs"]:
            # --- ⚡ 최초 관측 또는 50km/30km 거리 단계가 바뀔 때만 발송 ---
            transition = lightning_transition(s.get("last_lightning_level"), lightning_level)
            if transition:
                title, body = build_message(transition, dist=nearest)
                ok, status = send_web_push(s["subscription"], title, body)
                if ok:
                    mark_lightning(s["id"], lightning_level)
                elif status in (404, 410):
                    deactivate(s["id"])


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
