# -*- coding: utf-8 -*-
"""
번개 추적기 — 발송 엔진
GitHub Actions에서 10분마다 실행. 동작 순서:
  1) Supabase에서 구독자(동네·격자·웹푸시토큰) 읽기
  2) 같은 격자끼리 묶어 기상청에 천둥/낙뢰·소나기 조회 (API 절약)
  3) 천둥 감지된 격자의 구독자에게 웹푸시 발송
  4) 같은 사람은 30분 내 재알림 안 함(쿨다운)

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

WARNING_RADIUS_KM = float(os.environ.get("WARNING_RADIUS_KM", "10"))  # 10km 이내: 임박
WATCH_RADIUS_KM = float(os.environ.get("WATCH_RADIUS_KM", "30"))      # 30km 이내: 접근
COOLDOWN_MIN = int(os.environ.get("COOLDOWN_MIN", "30"))              # 강수예보 기본 간격(가입자 미선택 시)
LIGHTNING_COOLDOWN_MIN = int(os.environ.get("LIGHTNING_COOLDOWN_MIN", "30"))  # 낙뢰: 같은 단계 유지 시 간격(분). 단계 상승은 즉시
RAIN_FORECAST_HOURS = int(os.environ.get("RAIN_FORECAST_HOURS", "3"))  # 앞으로 N시간 내 강수예보를 봄(시야 범위). 10분마다 재확인하며 가까워질수록 정확해짐

# 낙뢰 단계 순위 (높을수록 위급). 단계가 올라가면 쿨다운 무시하고 즉시 발송
LIGHTNING_RANK = {"watch": 1, "warning": 2}
THUNDER_SOUND_URL = os.environ.get("THUNDER_SOUND_URL", "https://youtu.be/lpi6gd1H0Ok")

PTY_TEXT = {0: "강수 없음", 1: "비", 2: "비/눈", 3: "눈", 5: "빗방울", 6: "빗방울/눈날림", 7: "눈날림"}


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
def fetch_lightning_data(lat, lon, range_km):
    """기상청 API허브 최근 낙뢰 좌표 목록"""
    url = "https://apihub.kma.go.kr/api/typ01/url/lgt_pnt.php"
    params = {
        "tm": datetime.now().strftime("%Y%m%d%H%M"),
        "itv": 15, "lon": lon, "lat": lat, "range": range_km,
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


def fetch_forecast(nx, ny):
    """초단기예보로 향후 RAIN_FORECAST_HOURS 시간 내 강수(소나기) 예보 확인"""
    now = datetime.now()
    t = now - timedelta(minutes=45)
    if t.minute < 30:
        t = t - timedelta(hours=1)
    url = ("https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0/getUltraSrtFcst")
    params = {
        "pageNo": 1, "numOfRows": 300, "dataType": "JSON",
        "base_date": t.strftime("%Y%m%d"), "base_time": t.strftime("%H30"),
        "nx": nx, "ny": ny, "authKey": KMA_API_KEY,
    }
    try:
        items = http_get(url, params).json()["response"]["body"]["items"]["item"]
        rains = []
        for it in items:
            if it.get("category") != "PTY":
                continue
            pty = int(float(it.get("fcstValue", 0)))
            if pty == 0:
                continue
            ft = datetime.strptime(it["fcstDate"] + it["fcstTime"], "%Y%m%d%H%M")
            if now <= ft <= now + timedelta(hours=RAIN_FORECAST_HOURS):
                rains.append((ft, pty))
        if not rains:
            return None
        rains.sort()
        ft, pty = rains[0]
        return {"time": ft, "pty": pty, "pty_text": PTY_TEXT.get(pty, "비"), "mins": int((ft - now).total_seconds() // 60)}
    except Exception as e:
        print(f"[예보 조회 실패] {e}")
        return None


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
        "select": "id,dog_name,lat,lon,nx,ny,dong,subscription,last_notified_at,cooldown_min,last_lightning_at,last_lightning_level",
        "active": "eq.true",
    }
    res = requests.get(url, headers=sb_headers(), params=params, timeout=30)
    res.raise_for_status()
    # 웹푸시 토큰 있는 사람만
    return [s for s in res.json() if s.get("subscription")]


def mark_notified(sub_id):
    """강수예보 알림 시각 갱신"""
    url = f"{SUPABASE_URL}/rest/v1/subscribers"
    now = datetime.now(timezone.utc).isoformat()
    try:
        requests.patch(url, headers=sb_headers(), params={"id": f"eq.{sub_id}"},
                       json={"last_notified_at": now}, timeout=15)
    except Exception as e:
        print(f"[last_notified 갱신 실패] {e}")


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


def cooldown_ok(sub):
    """강수예보 발송 가능 여부 — 가입자가 고른 간격(cooldown_min) 적용"""
    ts = sub.get("last_notified_at")
    if not ts:
        return True
    # 가입자가 고른 간격(cooldown_min). 없으면 기본 COOLDOWN_MIN(30분)
    cd = sub.get("cooldown_min") or COOLDOWN_MIN
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last) > timedelta(minutes=cd)
    except Exception:
        return True


def lightning_should_send(sub, cur_level):
    """낙뢰 경보 발송 여부 (가입자 간격과 독립).
    단계가 올라가면(접근→임박, 또는 처음 감지) 즉시,
    같은 단계가 이어지면 LIGHTNING_COOLDOWN_MIN(기본 30분) 간격."""
    prev_level = sub.get("last_lightning_level")
    if LIGHTNING_RANK[cur_level] > LIGHTNING_RANK.get(prev_level, 0):
        return True  # 단계 상승(또는 처음) → 즉시
    ts = sub.get("last_lightning_at")
    if not ts:
        return True
    try:
        last = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - last) > timedelta(minutes=LIGHTNING_COOLDOWN_MIN)
    except Exception:
        return True


# ----------------------------------------------------------------
# 웹푸시 발송
# ----------------------------------------------------------------
def send_web_push(subscription, title, body, url=THUNDER_SOUND_URL):
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
def build_message(alert_type, dog, fc=None, dist=None):
    km = round(dist) if dist is not None else None
    if alert_type == "warning":
        return (f"🐾⚡ 천둥 코앞 (약 {km}km)",
                f"약 {km}km 거리까지 낙뢰가 왔어요! 천둥소리 볼륨 올리고 {dog} 안심시켜주세요.")
    if alert_type == "watch":
        return (f"🐾 천둥 접근 중 (약 {km}km)",
                f"약 {km}km 거리에서 낙뢰 감지. 진짜 천둥 오기 전에 천둥소리 미리 틀어 {dog}가 익숙해지게 🎧")
    # forecast
    eta = fc["time"].strftime("%H:%M")
    return (f"🐾🌧 곧 비 올 듯 — {dog} 적응 준비!",
            f"약 {fc['mins']}분 뒤({eta}쯤) {fc['pty_text']} 예보. 미리 천둥소리 틀어두세요 🎧")


# ----------------------------------------------------------------
# 한 번 확인 (클라우드에서 10분마다 호출)
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
                lightning_level = "warning"   # 10km 이내: 임박
            elif nearest <= WATCH_RADIUS_KM:
                lightning_level = "watch"      # 30km 이내: 접근

        # 2) 강수 예보(1시간 이내) — 낙뢰 없을 때만 확인(천둥이 우선)
        fc = fetch_forecast(nx, ny) if lightning_level is None else None

        if lightning_level is None and fc is None:
            print(f"  격자({nx},{ny}) {g.get('dong') or ''}: 천둥/소나기 없음")
            # 낙뢰가 사라졌으니 단계 리셋 → 다음 천둥 때 다시 즉시 알림
            for s in g["subs"]:
                if s.get("last_lightning_level"):
                    reset_lightning(s["id"])
            continue

        print(f"  격자({nx},{ny}) {g.get('dong') or ''}: "
              f"낙뢰={lightning_level or '없음'} / 예보={'비' if fc else '없음'} → {len(g['subs'])}명 처리")

        for s in g["subs"]:
            dog = s.get("dog_name") or "강아지"

            # --- ⚡ 낙뢰 경보: 가입자 간격과 독립, 무조건 ---
            if lightning_level:
                if lightning_should_send(s, lightning_level):
                    title, body = build_message(lightning_level, dog, dist=nearest)
                    ok, status = send_web_push(s["subscription"], title, body)
                    if ok:
                        mark_lightning(s["id"], lightning_level)
                    elif status in (404, 410):
                        deactivate(s["id"])
                continue  # 천둥 상황에선 강수예보 알림은 보내지 않음(천둥이 우선)

            # 낙뢰 없음 → 단계 리셋
            if s.get("last_lightning_level"):
                reset_lightning(s["id"])

            # --- 🌧 강수 예보: 가입자가 고른 간격(10/20/30분) ---
            if fc and cooldown_ok(s):
                title, body = build_message("forecast", dog, fc)
                ok, status = send_web_push(s["subscription"], title, body)
                if ok:
                    mark_notified(s["id"])
                elif status in (404, 410):
                    deactivate(s["id"])


# ----------------------------------------------------------------
# 테스트: 날씨 무관하게 모든 구독자에게 1회 푸시 (발송 연결 확인용)
# ----------------------------------------------------------------
def run_test():
    subs = get_subscribers()
    print(f"구독자 {len(subs)}명에게 테스트 푸시")
    for s in subs:
        dog = s.get("dog_name") or "강아지"
        ok, status = send_web_push(
            s["subscription"],
            "🐾 번개 추적기 테스트",
            f"{dog} 알림 연결 성공! 천둥이 오면 이렇게 미리 알려드릴게요.",
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

    parser = argparse.ArgumentParser(description="번개 추적기 발송 엔진")
    parser.add_argument("--once", action="store_true", help="한 번 확인하고 종료(클라우드용)")
    parser.add_argument("--test", action="store_true", help="모든 구독자에게 테스트 푸시")
    args = parser.parse_args()

    if not validate_config(need_kma=not args.test):
        raise SystemExit(1)

    if args.test:
        run_test()
    else:
        run_once()
