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
import hashlib
import json
import math
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit, urlunsplit

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
# 다만 코앞은 다르다. 5km에 한 발만 떨어져도 준비할 이유가 되므로,
# 이 거리 안쪽은 개수를 따지지 않고 감지 즉시 알린다(2026-08-22 사용자 결정).
NEAR_RADIUS_KM = float(os.environ.get("NEAR_RADIUS_KM", "10"))

# 같은 사람에게 이 간격 안에 두 번 보내지 않는다.
# 구간 경계(예: 10km↔20km)를 오가면 '가까워짐/멀어짐'이 번갈아 나가 도배가 된다.
MIN_ALERT_GAP_MINUTES = int(os.environ.get("MIN_ALERT_GAP_MINUTES", "10"))

# 낙뢰가 가까워질 때마다 알리기 위한 거리 구간(km, 바깥→안쪽).
# 예전에는 50km(접근)/30km(임박) 두 단계뿐이라, 30km 안에 들어오고 나면
# 25km→15km→8km로 다가와도 알림이 한 번도 안 갔다(2026-08-21 지적).
# 한 구간 더 안쪽으로 들어올 때마다 한 번씩 알린다.
ALERT_BANDS = [int(x) for x in os.environ.get("ALERT_BANDS", "50,40,30,20,10").split(",")]
# 10km 이내 최초 알림 뒤에도 낙뢰가 계속되면 한 번만 재알림한다.
# 매 주기마다 울리면 사용자가 알림을 꺼버릴 수 있으므로, 단계 값에 reminded 상태를
# 함께 저장해 같은 뇌우에서는 반복하지 않는다.
NEARBY_REMINDER_MINUTES = int(os.environ.get("NEARBY_REMINDER_MINUTES", "10"))

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
# 기상청 접속 재시도 정책 (2026-08-22 강화).
# 전국에 뇌우가 칠 때 GitHub 러너(미국)→기상청 연결이 자주 끊긴다.
# 같은 시각 국내 PC에서는 0.2초에 성공하므로 기상청이 죽은 게 아니라 경로 문제다.
# 예전엔 30초×3회=90초에 포기해서 한 주기를 통째로 날렸다(2026-08-22 6회 중 3회 실패).
# 연결 실패는 빨리 드러나므로 접속 대기를 10초로 줄이고 횟수를 늘린다.
HTTP_CONNECT_TIMEOUT = float(os.environ.get("HTTP_CONNECT_TIMEOUT", "10"))
HTTP_READ_TIMEOUT = float(os.environ.get("HTTP_READ_TIMEOUT", "30"))
HTTP_TRIES = int(os.environ.get("HTTP_TRIES", "6"))
HTTP_BACKOFF = [3, 6, 10, 15, 20]          # 재시도 간격(초)
# 5분 주기를 넘기면 다음 실행과 겹친다. 이 시간을 넘기면 더 시도하지 않는다.
HTTP_DEADLINE_SEC = float(os.environ.get("HTTP_DEADLINE_SEC", "150"))


def http_get(url, params, tries=None, timeout=None):
    tries = tries or HTTP_TRIES
    timeout = timeout or (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)
    started = time.monotonic()
    last_err = None
    for attempt in range(1, tries + 1):
        try:
            res = KMA_SESSION.get(url, params=params, timeout=timeout)
            res.raise_for_status()
            if attempt > 1:
                print(f"[기상청 재시도 성공] {attempt}번째 시도 "
                      f"({time.monotonic() - started:.0f}초 걸림)")
            return res
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt >= tries:
                break
            wait = HTTP_BACKOFF[min(attempt - 1, len(HTTP_BACKOFF) - 1)]
            if time.monotonic() - started + wait + HTTP_CONNECT_TIMEOUT > HTTP_DEADLINE_SEC:
                print(f"[기상청] {HTTP_DEADLINE_SEC:.0f}초 넘겨 재시도 중단 — 다음 주기에 맡긴다")
                break
            print(f"[기상청 재시도] {attempt}/{tries} 실패({type(e).__name__}) — {wait}초 뒤 다시")
            time.sleep(wait)
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


# 관리자용 "남한 낙뢰 감지" 알림 — 개인 안전·모니터링 목적이라 국경선을
# 정밀하게 그릴 필요는 없다. 휴전선은 서쪽(개성 부근 37.95N)이 낮고 동쪽
# (고성 부근 38.6N)이 높은 대각선이라, 직선 위도 컷 대신 그 기울기를
# 선형으로 근사한다. 개성 인근에서 낙뢰가 남한으로 오탐될 여지는 있지만
# 안전 알림 용도로는 무해하다.
def is_south_korea(lat, lon):
    if not (33.0 <= lat <= 38.65 and 124.5 <= lon <= 131.9):
        return False
    dmz_lat = 37.95 + (lon - 126.0) * (38.6 - 37.95) / (128.4 - 126.0)
    return lat <= dmz_lat + 0.15  # 여유 0.15도(~17km)


# 관리자 알림 메시지에 지역명을 붙이기 위한 주요 도시 (남한만)
_SK_CITIES = [
    ("서울", 37.5665, 126.9780), ("인천", 37.4563, 126.7052), ("수원", 37.2636, 127.0286),
    ("춘천", 37.8813, 127.7298), ("강릉", 37.7519, 128.8761), ("원주", 37.3422, 127.9202),
    ("청주", 36.6424, 127.4890), ("대전", 36.3504, 127.3845), ("천안", 36.8151, 127.1139),
    ("전주", 35.8242, 127.1480), ("군산", 35.9678, 126.7369), ("광주", 35.1595, 126.8526),
    ("목포", 34.8118, 126.3922), ("여수", 34.7604, 127.6622), ("순천", 34.9506, 127.4872),
    ("대구", 35.8714, 128.6014), ("포항", 36.0190, 129.3435), ("안동", 36.5684, 128.7294),
    ("부산", 35.1796, 129.0756), ("울산", 35.5384, 129.3114), ("창원", 35.2280, 128.6811),
    ("진주", 35.1800, 128.1076), ("제주", 33.4996, 126.5312), ("서귀포", 33.2541, 126.5601),
    ("속초", 38.2070, 128.5918), ("충주", 36.9910, 127.9259), ("경주", 35.8562, 129.2247),
]


def _sk_city_labels(strikes, limit=3):
    """낙뢰 좌표들에서 가장 가까운 도시 이름을 뽑아 중복 없이 최대 limit개."""
    seen, out = set(), []
    for lat, lon in strikes:
        city, dist = min(((c, haversine(lat, lon, c[1], c[2])) for c in _SK_CITIES),
                          key=lambda x: x[1])
        name = city[0] if dist <= 40 else f"{city[0]} 인근"
        if name not in seen:
            seen.add(name)
            out.append(name)
        if len(out) >= limit:
            break
    return out


def check_sk_master_alert(strikes):
    """남한 어디서든 낙뢰가 '새로 시작'될 때만 관리자에게 텔레그램 1회.

    가입자 수와 무관하게 항상 확인한다(개인 모니터링·SNS 홍보 트리거 목적).
    0건→1건 이상 전환에서만 보낸다 — 뇌우가 계속되는 동안 5분마다 오면
    금세 무시하게 된다. 잠잠해지면 자동으로 다시 무장되어 다음 뇌우 때 또 알린다.
    """
    sk = [(lat, lon) for lat, lon in strikes if is_south_korea(lat, lon)]
    hb = read_heartbeat() or {}
    was_active = bool(hb.get("sk_active"))

    if not sk:
        if was_active:
            hb["sk_active"] = False
            _put_heartbeat(hb)
        return

    if was_active:
        return  # 이미 알렸고 계속되는 중 — 조용히 넘어간다

    labels = _sk_city_labels(sk)
    where = ", ".join(labels) if labels else "지역 확인 중"
    notify_admin(f"⚡ 남한에서 낙뢰가 감지되기 시작했습니다\n"
                 f"{datetime.now(KST):%H:%M} 기준 {len(sk)}건 · {where}")
    hb["sk_active"] = True
    hb["sk_active_since"] = datetime.now(KST).isoformat(timespec="seconds")
    _put_heartbeat(hb)


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
    # 통째로 새 dict를 덮어쓰면 check_sk_master_alert()가 남겨둔 sk_active 같은
    # 다른 필드가 지워진다. 읽어서 병합한다(record_failure()와 같은 방식).
    hb = read_heartbeat() or {}
    hb.update({
        "last_success": datetime.now(KST).isoformat(timespec="seconds"),
        "sent": sent_count,
        "strikes": strike_count,
        "fail_streak": 0,          # 성공했으니 연속 실패 기록을 지운다
    })
    _put_heartbeat(hb)


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
    rows = [s for s in res.json() if s.get("subscription")]
    return dedupe_by_endpoint(rows)


def dedupe_by_endpoint(rows):
    """같은 기기(엔드포인트)가 여러 번 등록됐으면 가장 최근 것만 남긴다.

    홈화면에 다시 추가하거나 알림을 재설정하면 새 구독이 발급되는데,
    가입 시 기존 행을 확인하지 않아 행이 쌓인다. 그대로 두면 한 기기에
    알림이 두 번, 세 번 간다(2026-08-21 제보).
    created_at 오름차순으로 들어오므로 뒤에 오는 것이 최신이다.
    """
    latest, losers = {}, []
    for r in rows:
        sub = r.get("subscription") or {}
        ep = sub.get("endpoint") if isinstance(sub, dict) else None
        key = ep or r["id"]
        if key in latest:
            losers.append(latest[key])     # 앞의 것이 더 오래된 행
        latest[key] = r                    # 나중 것(최신)이 남는다
    if losers:
        print(f"[중복 구독] {len(rows)}건 중 {len(losers)}건은 같은 기기 — 옛 행을 비활성화합니다")
        for r in losers:
            deactivate(r["id"])            # 다음 주기부터는 아예 조회되지 않는다
    return list(latest.values())


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


def issue_manage_token(sub_id):
    """알림 링크에서 이 구독 한 건만 끌 수 있는 관리 토큰을 발급한다.

    원문 토큰은 푸시 링크에만 넣고 DB에는 SHA-256 해시만 저장한다.
    새 알림을 보낼 때마다 교체하므로 이전 알림의 링크는 자동으로 무효화된다.
    실패해도 낙뢰 알림 자체는 막지 않고 관리 링크만 생략한다.
    """
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    try:
        res = SB_SESSION.patch(
            url,
            headers=sb_headers(),
            params={"id": f"eq.{sub_id}"},
            json={"manage_token_hash": token_hash},
            timeout=15,
        )
        if not res.ok:
            print(f"[관리 토큰 저장 실패] {res.status_code} {res.text[:150]}")
            return None
        return token
    except Exception as e:
        print(f"[관리 토큰 저장 실패] {e}")
        return None


def build_manage_url(base_url, token):
    """토큰을 서버 로그에 남기지 않도록 URL fragment에 넣는다."""
    if not token:
        return base_url
    parts = urlsplit(base_url)
    anchor = (parts.fragment or "radar").split("&manage=", 1)[0]
    fragment = f"{anchor}&manage={quote(token, safe='')}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, fragment))


def send_subscriber_push(subscriber, title, body):
    """기존 발송과 관리 링크 발급을 묶되, 링크 실패는 발송 실패로 취급하지 않는다."""
    token = issue_manage_token(subscriber["id"])
    url = build_manage_url(ALERT_CLICK_URL, token)
    return send_web_push(subscriber["subscription"], title, body, url=url)


def band_of(km):
    """이 거리가 속한 구간(km). 가장 바깥 구간보다 멀면 None."""
    if km is None:
        return None
    inner = None
    for b in sorted(ALERT_BANDS):
        if km <= b:
            inner = b
            break
    return inner


def _as_band(level):
    """DB에 저장된 값을 구간 숫자로. 옛 표기(watch/warning)도 받아준다."""
    if level in (None, "", "none"):
        return None
    if level == "watch":
        return 50
    if level == "warning":
        return 30
    try:
        return int(str(level).split(":", 1)[0])
    except (TypeError, ValueError):
        return None


def _reminder_sent(level):
    """10:reminded처럼 같은 뇌우의 지속 알림 발송 여부를 읽는다."""
    return isinstance(level, str) and level.endswith(":reminded")


def _minutes_since(value, now=None):
    """Supabase ISO 시각으로부터 지난 분. 값이 없거나 손상되면 None."""
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0, (current - stamp.astimezone(timezone.utc)).total_seconds() / 60)
    except (TypeError, ValueError):
        return None


def nearby_reminder_due(previous_level, current_level, last_alert_at, now=None):
    """10km 단계가 계속될 때 10분 후 지속 알림을 한 번만 허용한다."""
    if _as_band(previous_level) != 10 or _as_band(current_level) != 10:
        return False
    if _reminder_sent(previous_level):
        return False
    elapsed = _minutes_since(last_alert_at, now=now)
    return elapsed is not None and elapsed >= NEARBY_REMINDER_MINUTES


def lightning_transition(prev_level, cur_level):
    """구간이 안쪽으로 바뀔 때마다 알린다.

    바깥으로 물러나면 한 번만 알리고 기준을 갱신한다. 그래야 다시
    다가올 때 또 알릴 수 있다. 같은 구간에 머무르면 보내지 않는다.
    """
    prev, cur = _as_band(prev_level), _as_band(cur_level)
    if cur is None:
        return None
    if prev is None:
        return "initial"          # 이번 뇌우의 첫 알림
    if cur < prev:
        return "closer"           # 한 구간 더 가까워짐
    if cur > prev:
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
    """실제 거리를 그대로 알려주고, 레이더를 열어볼 이유를 붙인다.

    제목에 서비스명을 다시 넣지 않는다 — 알림에는 이미 앱 이름이 뜨므로
    자리만 먹는다. 대신 거리를 앞세워 잠금화면에서 바로 읽히게 한다.
    본문 끝의 안내는 유형마다 다르게 준다. 셋 다 "확인해 주세요"로 끝나면
    금세 읽지 않게 되고, 알림만 보고 끝나면 서비스가 거기서 끝난다.
    """
    km = round(dist) if dist is not None else None
    if alert_type == "initial":
        head = "🚨" if (km is not None and km <= 30) else "⚡"
        return (f"{head} 약 {km}km 앞에 낙뢰",
                f"우리 동네에서 약 {km}km 떨어진 곳에 번개가 쳤어요. "
                f"어디까지 왔는지 썬더미리 레이더에서 확인해 보세요.")
    if alert_type == "closer":
        head = "🚨" if (km is not None and km <= 30) else "⚡"
        return (f"{head} 낙뢰가 {km}km까지 왔어요",
                f"조금 전보다 가까워졌어요. 지금 어디쯤인지, 우리 쪽으로 오는지 "
                f"썬더미리에서 보고 준비하세요.")
    if alert_type == "farther":
        return (f"↗️ 낙뢰가 {km}km로 멀어졌어요" if km is not None else "↗️ 낙뢰가 멀어졌어요",
                f"지나가는 중입니다. 다시 가까워지는지 썬더미리 레이더에서 확인해 보세요.")
    if alert_type == "nearby_still":
        return ("🚨 10km 안에서 낙뢰가 계속되고 있어요",
                "가까운 곳에서 낙뢰가 계속 관측되고 있습니다. "
                "썬더미리 레이더에서 현재 위치를 확인해 주세요.")
    raise ValueError(f"지원하지 않는 알림 유형: {alert_type}")


# ----------------------------------------------------------------
# 한 번 확인 (클라우드에서 5분마다 호출)
# ----------------------------------------------------------------
def run_once():
    # 지난 주기들이 통째로 비어 있었는지 먼저 확인한다(복구 시점에 알리기 위함)
    check_missed_runs()

    # 전국 낙뢰를 한 번만 받아온다. 이후 거리 계산은 각자의 좌표로 우리가 직접 한다.
    # (격자로 묶어 조회하던 방식은 가입자가 흩어질수록 기상청 호출이 늘어 한도에 걸렸다)
    # ⚠️ 구독자 유무 확인보다 먼저 온다 — 남한 마스터 알림(check_sk_master_alert)은
    # 구독자가 0명이어도 항상 동작해야 하는 운영자 전용 채널이기 때문이다.
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

    # 운영자 전용. 구독자에게 가는 send_web_push()와는 완전히 다른 통로(텔레그램)이고
    # 완전히 다른 함수다 — 절대 섞이지 않는다.
    check_sk_master_alert(strikes)

    subs = get_subscribers()
    if not subs:
        print(f"[{datetime.now():%H:%M:%S}] 구독자 없음(또는 푸시토큰 없음). 전국 낙뢰 {len(strikes)}건 확인만 하고 종료.")
        return

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

        # 1) 낙뢰 거리 → 구간(ALERT_BANDS) — 예보가 아니라 '실측' 기반
        #    거리만 보지 않고 개수도 본다. 외딴 한 발은 뇌우 접근이 아니다.
        #    단계 값에는 구간 숫자를 넣는다. 가까워질 때마다 알리려면
        #    watch/warning 두 값으로는 30km 안쪽의 변화를 표현할 수 없다.
        nearest, watch_n, warn_n = strike_summary(lat, lon, strikes)
        lightning_level = None
        if nearest is not None:
            band = band_of(nearest)
            if nearest <= NEAR_RADIUS_KM:
                enough = True                      # 코앞은 한 발이라도 알린다
            elif nearest <= WARNING_RADIUS_KM:
                enough = warn_n >= MIN_STRIKES
            else:
                enough = watch_n >= MIN_STRIKES
            if band is not None and enough:
                lightning_level = str(band)
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
        previous_level = s.get("last_lightning_level")
        transition = lightning_transition(previous_level, lightning_level)
        # 이미 10km 단계 알림을 받았고 근거리 낙뢰가 10분 이상 이어지는 경우,
        # 같은 뇌우에서 딱 한 번만 지속 알림을 보낸다.
        if (not transition and nearby_reminder_due(
                previous_level, lightning_level, s.get("last_lightning_at"))):
            transition = "nearby_still"
        if not transition:
            continue

        # 구간을 오갈 때 5분마다 울리지 않도록 최소 간격을 둔다.
        # 건너뛰어도 단계를 갱신하지 않으므로, 간격이 지나면 그때 발송된다.
        since = _minutes_since(s.get("last_lightning_at"))
        if since is not None and since < MIN_ALERT_GAP_MINUTES:
            print(f"  {s.get('dong') or ''}: {transition} 이지만 "
                  f"{since:.0f}분 전에 보냈음 — {MIN_ALERT_GAP_MINUTES}분 간격 유지")
            continue

        title, body = build_message(transition, dist=nearest)
        ok, status = send_subscriber_push(s, title, body)
        if ok:
            marked_level = "10:reminded" if transition == "nearby_still" else lightning_level
            pending_marks.append((s["id"], marked_level))
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
        ok, status = send_subscriber_push(
            s,
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
    parser.add_argument("--admin-test", action="store_true",
                         help="관리자 텔레그램 연결 테스트(구독자에겐 절대 안 감, 나에게만)")
    args = parser.parse_args()

    if args.admin_test:
        # 구독자 경로(send_web_push)는 아예 호출하지 않는다 — notify_admin()만 쓴다.
        ok = notify_admin("[테스트] 텔레그램 연결 확인용 메시지입니다.\n"
                          "남한에 낙뢰가 감지되면 이런 식으로 옵니다. 실제 낙뢰와는 무관합니다.")
        raise SystemExit(0 if ok else 1)

    if not validate_config(need_kma=not args.test):
        raise SystemExit(1)

    if args.test:
        run_test()
    else:
        run_once()
