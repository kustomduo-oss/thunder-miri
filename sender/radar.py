# -*- coding: utf-8 -*-
"""
동탄이네 천둥번개 알림이 — 레이더 화면용 이미지 생성기

하는 일:
  1) 기상청 레이더 합성자료(전국 격자 숫자)를 받아
  2) 구독자가 있는 동네 주변만 잘라내고
  3) 강수 강도에 따라 색을 입혀 PNG로 만든 뒤
  4) Supabase Storage에 올린다 (지도에 얹을 위경도 범위도 함께 저장)

핵심 개념: 기상청은 '숫자 표'를 준다. 사람이 보려면 색을 입혀야 한다.
          (엑셀 조건부 서식과 같은 일)

⚠️ 이미지는 git 저장소에 넣지 않는다(매 5분마다 쌓이면 저장소가 부푼다).
   대신 Supabase Storage에 같은 이름으로 덮어쓴다.
"""
import io
import json
import os
import struct
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import requests
from PIL import Image
from pyproj import CRS, Transformer

# ── 설정 ───────────────────────────────────────────────
KMA_API_KEY = os.environ.get("KMA_API_KEY", "").strip()
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://pdlohzenslwbiyoxwjom.supabase.co").strip()
SUPABASE_SECRET_KEY = os.environ.get("SUPABASE_SECRET_KEY", "").strip()

RADAR_URL = "https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-rdr_cmp1_api"
BUCKET = "radar"
CROP_KM = float(os.environ.get("RADAR_CROP_KM", "520"))   # 우리집 기준 ±거리(넓게 보이도록)
OUT_PX = int(os.environ.get("RADAR_OUT_PX", "900"))       # 출력 이미지 한 변
LOCAL_RAIN_RADIUS_KM = float(os.environ.get("LOCAL_RAIN_RADIUS_KM", "5"))

# 기상청 레이더 합성 격자의 투영법 (검증 완료: 청주·서울·부산·제주·울릉도 모두 일치)
RADAR_CRS = CRS.from_proj4(
    "+proj=lcc +lat_1=30 +lat_2=60 +lat_0=38 +lon_0=126 "
    "+x_0=0 +y_0=0 +ellps=WGS84 +units=km +no_defs"
)
_fwd = Transformer.from_crs("EPSG:4326", RADAR_CRS, always_xy=True)   # 위경도 → 격자평면
_inv = Transformer.from_crs(RADAR_CRS, "EPSG:4326", always_xy=True)   # 격자평면 → 위경도
GRID_KM = 0.5

# 강수 강도(dBZ)별 색 — 기상청 레이더와 비슷한 계열
COLOR_STEPS = [
    (0,  (142, 209, 252)),   # 아주 약한 비
    (10, (58, 160, 255)),
    (20, (46, 204, 113)),    # 보통
    (30, (241, 196, 15)),
    (40, (230, 126, 34)),    # 강한 비
    (50, (231, 76, 60)),     # 매우 강함
]

NO_ECHO = -25000     # 관측영역 안이지만 비 없음
OUT_OF_RANGE = -30000  # 관측영역 밖


# 이 스크립트는 5분마다 실행된다. 한 번이 5분을 넘기면 다음 실행에 취소돼
# 그 주기의 레이더가 통째로 사라진다(실측: 12회 중 4회 취소, 5~7.5분 소요).
# 알림을 받고 레이더를 보러 온 사람에게 낡은 화면을 보여주게 되므로,
# "느리면 포기하고 다음 주기에 다시" 하는 편이 낫다.
RADAR_TIMEOUT = int(os.environ.get("RADAR_TIMEOUT", "60"))       # 1회 수신 상한(초)
QPF_TIMEOUT = int(os.environ.get("QPF_TIMEOUT", "45"))           # 예측 1장 상한(초)
DEADLINE_SEC = int(os.environ.get("RADAR_DEADLINE_SEC", "210"))  # 전체 마감(3분 30초)
_started = time.monotonic()


def over_deadline(what=""):
    """마감을 넘겼으면 True. 남은 작업을 건너뛰고 이미 만든 것만 남긴다."""
    if time.monotonic() - _started > DEADLINE_SEC:
        print(f"[마감] {DEADLINE_SEC}초 초과 — {what} 건너뜀 (다음 주기에 다시 만듭니다)")
        return True
    return False


def fetch_radar(tm=None, tries=3):
    """레이더 합성자료(binary) 수신. 최신 파일이 아직 없을 수 있어 시각을 거슬러 재시도."""
    now = datetime.now()
    for k in range(tries):
        t = tm or (now - timedelta(minutes=15 + k * 5))
        stamp = t.replace(minute=(t.minute // 5) * 5, second=0).strftime("%Y%m%d%H%M")
        try:
            res = requests.get(RADAR_URL, params={
                "tm": stamp, "cmp": "HSR", "qcd": "KMA", "obs": "ECHO",
                "map": "HB", "disp": "B", "authKey": KMA_API_KEY,
            }, timeout=RADAR_TIMEOUT)
            # 정상 응답은 수 MB. 짧으면 "자료가 없습니다" 같은 안내문.
            if len(res.content) > 100000:
                return res.content, stamp
            print(f"[레이더] {stamp} 자료 없음 → 이전 시각 재시도")
        except requests.exceptions.RequestException as e:
            print(f"[레이더] {stamp} 수신 실패: {e}")
        if tm:
            break
    return None, None


def to_grid_index(lat, lon, nx, ny):
    """위경도 → 격자 인덱스 (격자 중심이 투영 원점)"""
    x, y = _fwd.transform(lon, lat)
    return x / GRID_KM + nx / 2, y / GRID_KM + ny / 2


def view_bounds(lat, lon):
    """우리집 기준 ±CROP_KM 상자를 감싸는 위경도 범위.
    레이더 격자는 LCC 투영이라 위경도로 보면 사각형이 아니다.
    네 변을 훑어 실제 최소·최대 위경도를 구해야 지도에 정확히 얹힌다."""
    cx, cy = _fwd.transform(lon, lat)
    xs = np.linspace(cx - CROP_KM, cx + CROP_KM, 60)
    ys = np.linspace(cy - CROP_KM, cy + CROP_KM, 60)
    gx, gy = np.meshgrid(xs, ys)
    lons, lats = _inv.transform(gx.ravel(), gy.ravel())
    return {"south": float(np.min(lats)), "north": float(np.max(lats)),
            "west": float(np.min(lons)), "east": float(np.max(lons))}


def latlon_sample_grid(bounds, px):
    """출력 이미지(위경도 정사각 격자)의 각 픽셀에 대응하는 LCC 좌표를 만든다.
    이렇게 재투영해야 넓은 범위에서도 한반도가 비뚤어지지 않는다."""
    lat = np.linspace(bounds["north"], bounds["south"], px)
    lon = np.linspace(bounds["west"], bounds["east"], px)
    lon2, lat2 = np.meshgrid(lon, lat)
    x, y = _fwd.transform(lon2.ravel(), lat2.ravel())
    return np.asarray(x).reshape(px, px), np.asarray(y).reshape(px, px)


def render(raw, lat, lon):
    """전국 격자를 위경도 격자로 재투영해 PNG(투명 배경) + 위경도 범위 반환"""
    nx, ny = struct.unpack("<hh", raw[:4])
    grid = np.frombuffer(raw[4:4 + nx * ny * 2], dtype="<i2").reshape(ny, nx)

    bounds = view_bounds(lat, lon)
    gx, gy = latlon_sample_grid(bounds, OUT_PX)
    ii = np.rint(gx / GRID_KM + nx / 2).astype(int)
    jj = np.rint(gy / GRID_KM + ny / 2).astype(int)
    inside = (ii >= 0) & (ii < nx) & (jj >= 0) & (jj < ny)
    vals = np.full((OUT_PX, OUT_PX), OUT_OF_RANGE, dtype=np.int32)
    vals[inside] = grid[jj[inside], ii[inside]]

    dbz = vals / 100.0
    rain = vals > NO_ECHO
    cx, cy = _fwd.transform(lon, lat)
    local_area = ((gx - cx) ** 2 + (gy - cy) ** 2) <= LOCAL_RAIN_RADIUS_KM ** 2
    local_rain = rain & local_area
    rgba = np.zeros((OUT_PX, OUT_PX, 4), dtype=np.uint8)
    for lo, c in COLOR_STEPS:
        m = rain & (dbz >= lo)
        rgba[m] = [c[0], c[1], c[2], 200]

    img = Image.fromarray(rgba, "RGBA")
    stats = {
        "rain_cells": int(rain.sum()),
        "total_cells": int(rain.size),
        "max_dbz": round(float(dbz[rain].max()), 1) if rain.any() else None,
        "local_rain_cells": int(local_rain.sum()),
        "local_total_cells": int(local_area.sum()),
        "local_max_dbz": round(float(dbz[local_rain].max()), 1) if local_rain.any() else None,
    }
    return img, bounds, stats


# ── 미래 강수예측(QPF) ──────────────────────────────────
# 기상청이 완성해서 주는 PNG(해안선·범례 포함). 관측 레이더와 달리
# '앞으로 비구름이 어디로 갈지'를 보여준다. ef = 예측시간(분).
QPF_URL = "https://apihub.kma.go.kr/api/typ03/cgi/dfs/nph-qpf_ana_img"
QPF_STEPS = [int(x) for x in os.environ.get("QPF_STEPS", "30,60,90,120,150,180,240,300,360").split(",")]


def build_forecast(lat, lon, key):
    """예측 프레임을 '우리 동네 투명 오버레이'로 만들어 Storage에 올린다.
    관측 레이더와 같은 범위·같은 방식이라 지도 위에서 이어서 볼 수 있다."""
    now = datetime.now()
    base = None
    for back in (30, 40, 50, 70):
        t = now - timedelta(minutes=back)
        stamp = t.replace(minute=(t.minute // 10) * 10, second=0)
        if _qpf_image(stamp, QPF_STEPS[0], map_code="HB"):
            base = stamp
            break
    if base is None:
        print("[예측] 사용 가능한 예측 자료 없음")
        return None

    frames, bounds = [], None
    for ef in QPF_STEPS:
        # 예측은 관측보다 뒤에 만든다. 늦어지면 여기서 끊어도
        # 낙뢰가 든 관측 JSON은 이미 올라가 있다.
        if over_deadline(f"예측 +{ef}분 이후"):
            break
        out = _qpf_overlay(base, ef, lat, lon)
        if not out or not out[0]:
            continue
        png, bnd, rain_px, local_rain_px, local_total_px = out
        url = upload(f"{key}_qpf_{ef}.png", png, "image/png")
        if url:
            bounds = bnd
            frames.append({
                "ef": ef,
                "valid_at": (base + timedelta(minutes=ef)).isoformat(),
                "image": url,
                "rain_px": rain_px,     # 지도에 보여줄 전체 비구름 픽셀 수
                "local_rain_px": local_rain_px,
                "local_total_px": local_total_px,
                "local_radius_km": LOCAL_RAIN_RADIUS_KM,
            })

    meta = {
        "base_time": base.isoformat(),
        "bounds": bounds,
        "frames": frames,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    upload(f"{key}_forecast.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"), "application/json")
    print(f"[예측] {base:%H:%M} 기준 {len(frames)}개 오버레이 생성 (+{QPF_STEPS[0]}~+{QPF_STEPS[-1]}분)")
    return meta


ments_note = """QPF 이미지 좌표 (실측으로 확정, 2026-08-11)
  map=HB, legend=0, size=600 → 600 x 770 PNG
  20행·769행이 지도 테두리선 → 지도영역 = rows 20..769(750px) x cols 0..599(600px)
  이 영역이 레이더 HB 격자(2305x2881 x 0.5km = 1152.5 x 1440.5km)와 동일.
  검증: 서울·부산·울릉도는 해안선 위, 서해/동해 먼바다는 빈 곳으로 정확히 떨어짐."""

QPF_TOP, QPF_MAPH, QPF_W = 20, 750, 600
HB_X_KM, HB_Y_KM = 2305 * GRID_KM, 2881 * GRID_KM     # 1152.5 x 1440.5 km


def fetch_lightning_national():
    """한반도와 주변 해역의 최근 1시간 낙뢰. sender의 조회 로직을 넓은 반경으로 재사용."""
    import sender as _s
    # 60을 넣으면 기상청이 최근 자료를 안 준다(0건). 59가 실질 상한이다.
    return _s.fetch_lightning_data(36.5, 127.8, 500, lookback_minutes=59)


def _qpf_overlay(base, ef, lat, lon):
    """예측 PNG에서 '비 색깔'만 남긴 투명 오버레이를 만든다.
    기상청 그림엔 해안선·배경이 그려져 있는데, 유채색(비)만 골라내면
    우리 지도 위에 그대로 겹칠 수 있다."""
    png = _qpf_image(base, ef, map_code="HB")
    if not png:
        return None, None
    src = np.array(Image.open(io.BytesIO(png)).convert("RGB")).astype(int)
    if src.shape[0] < QPF_TOP + QPF_MAPH:
        return None, None
    area = src[QPF_TOP:QPF_TOP + QPF_MAPH, :QPF_W]     # 테두리 안쪽 지도만

    # 관측과 똑같은 위경도 격자로 재투영 → 두 오버레이가 정확히 겹친다
    bounds = view_bounds(lat, lon)
    gx, gy = latlon_sample_grid(bounds, OUT_PX)
    cc = np.rint((gx + HB_X_KM / 2) / HB_X_KM * QPF_W).astype(int)
    rr = np.rint((HB_Y_KM / 2 - gy) / HB_Y_KM * QPF_MAPH).astype(int)
    inside = (cc >= 0) & (cc < QPF_W) & (rr >= 0) & (rr < QPF_MAPH)

    px = np.zeros((OUT_PX, OUT_PX, 3), dtype=int)
    px[inside] = area[rr[inside], cc[inside]]

    # 유채색(채도 높은 픽셀) = 강수. 흰 배경·회색 해안선은 버린다.
    rain = ((px.max(axis=2) - px.min(axis=2)) > 30) & inside
    cx, cy = _fwd.transform(lon, lat)
    local_area = (((gx - cx) ** 2 + (gy - cy) ** 2) <= LOCAL_RAIN_RADIUS_KM ** 2) & inside
    local_rain = rain & local_area
    rgba = np.zeros((OUT_PX, OUT_PX, 4), dtype=np.uint8)
    rgba[rain, :3] = px[rain]
    rgba[rain, 3] = 205

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, "PNG", optimize=True)
    return buf.getvalue(), bounds, int(rain.sum()), int(local_rain.sum()), int(local_area.sum())


def _qpf_image(base, ef, map_code="HR"):
    """예측 이미지 1장. 실패하거나 내용이 없으면 None."""
    try:
        res = requests.get(QPF_URL, params={
            "eva": 2, "tm": base.strftime("%Y%m%d%H%M"), "qpf": "B", "ef": ef,
            "map": map_code, "grid": 2, "legend": 0 if map_code == "HB" else 1, "size": 600,
            "zoom_level": 0, "zoom_x": 0, "zoom_y": 0, "authKey": KMA_API_KEY,
        }, timeout=QPF_TIMEOUT)
        # 정상은 PNG. 내용이 거의 없는 빈 프레임(수백 바이트)은 버린다.
        if res.content[:4] == b"\x89PNG" and len(res.content) > 3000:
            return res.content
    except requests.exceptions.RequestException as e:
        print(f"[예측] ef=+{ef} 수신 실패: {e}")
    return None


def upload(path, data, content_type):
    """Supabase Storage에 덮어쓰기 업로드 → 공개 URL 반환"""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}"
    res = requests.post(url, headers={
        "apikey": SUPABASE_SECRET_KEY,
        "Authorization": f"Bearer {SUPABASE_SECRET_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",
    }, data=data, timeout=60)
    if not res.ok:
        print(f"[업로드 실패] {path} {res.status_code} {res.text[:150]}")
        return None
    return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{path}"


# 격자 수 상한 (스팸·공격 대비 안전장치).
# 레이더는 격자 1곳당 QPF 9프레임 + 낙뢰 1회 = 기상청 ~10회 호출, 업로드 ~12개로 매우 무겁다.
# 실행이 5분(트리거 주기)을 넘기면 다음 실행에 밀려 취소되므로 발송(300)보다 훨씬 낮게 잡는다.
MAX_GRIDS = int(os.environ.get("RADAR_MAX_GRIDS", "50"))


# 과거 관측 프레임({key}_{stamp}.png) 생성은 2026-08-16에 중단됨.
# 이 프레임을 재생하던 radar.html이 삭제되어 읽는 곳이 없어졌기 때문.
# (히어로의 낙뢰 재생은 meta의 lightning[]만 쓰므로 영향 없음)
# 되살리려면: git show d11296a~1:radar.html 의 437행 부근 병합 로직 참고


def build_for(nx_grid, ny_grid, lat, lon, dong, lightning=None, raw=None, stamp=None, key=None):
    """한 동네(기상청 격자)에 대한 레이더 이미지 + 메타 생성·업로드"""
    if raw is None:
        raw, stamp = fetch_radar()
    if raw is None:
        return None

    img, bounds, stats = render(raw, lat, lon)
    if img is None:
        return None
    rain_cells = stats["rain_cells"]

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    png = buf.getvalue()

    key = key or f"{nx_grid}_{ny_grid}"
    img_url = upload(f"{key}.png", png, "image/png")

    obs = datetime.strptime(stamp, "%Y%m%d%H%M") if stamp else datetime.now()
    meta = {
        "grid": [nx_grid, ny_grid],
        "dong": dong,
        "home": {"lat": lat, "lon": lon},
        "bounds": bounds,
        "image": img_url,
        "rain_cells": rain_cells,
        "total_cells": stats["total_cells"],
        "max_dbz": stats["max_dbz"],
        "local_rain_cells": stats["local_rain_cells"],
        "local_total_cells": stats["local_total_cells"],
        "local_max_dbz": stats["local_max_dbz"],
        "local_radius_km": LOCAL_RAIN_RADIUS_KM,
        "observed_at": obs.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "lightning": lightning or [],
        "past": [],     # 과거 재생 중단(2026-08-16). 옛 JSON을 읽는 코드 호환용으로 빈 배열 유지
    }
    upload(f"{key}.json", json.dumps(meta, ensure_ascii=False).encode("utf-8"), "application/json")
    print(f"[레이더] {dong or key} 생성 완료 · 강수 {rain_cells:,}칸 · 낙뢰 {len(lightning or [])}건 · {stamp}")
    return meta


if __name__ == "__main__":
    import argparse
    import sender  # 구독자 목록·낙뢰 조회 재사용

    sender.load_local_env()
    for k in ["KMA_API_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY"]:
        globals()[k] = os.environ.get(k, globals().get(k, "")).strip()
        setattr(sender, k, globals()[k])

    ap = argparse.ArgumentParser(description="레이더 이미지 생성")
    ap.add_argument("--lat", type=float, help="테스트용 위도")
    ap.add_argument("--lon", type=float, help="테스트용 경도")
    ap.add_argument("--tm", help="테스트용 시각 YYYYMMDDHHMI")
    args = ap.parse_args()

    if args.lat and args.lon:
        tm = datetime.strptime(args.tm, "%Y%m%d%H%M") if args.tm else None
        raw, stamp = fetch_radar(tm=tm)
        build_for(0, 0, args.lat, args.lon, "테스트", raw=raw, stamp=stamp)
        raise SystemExit(0)

    # 구독자가 있는 격자마다 생성 (전국 자료는 한 번만 받아 재사용)
    subs = sender.get_subscribers()
    grids = {}
    for s in subs:
        grids.setdefault((s["nx"], s["ny"]), s)
    grids = sender.cap_grids(grids, MAX_GRIDS, "레이더")

    raw, stamp = fetch_radar()
    if raw is None:
        print("[레이더] 자료 수신 실패")
        raise SystemExit(1)

    # 전국판: 아직 가입하지 않은 방문자도 첫 화면에서 볼 수 있도록 항상 만든다
    NAT_LAT, NAT_LON = 36.5, 127.8
    try:
        nat_strikes = []
        for it in fetch_lightning_national():
            try:
                nat_strikes.append({
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "tm": it.get("tm"),
                })
            except (TypeError, ValueError):
                continue
        build_for(None, None, NAT_LAT, NAT_LON, "전국",
                  lightning=nat_strikes[:600], raw=raw, stamp=stamp, key="national")
        build_forecast(NAT_LAT, NAT_LON, "national")
    except Exception as e:
        print(f"[전국] 생성 실패(무시하고 계속): {e}")

    if not grids:
        print("[레이더] 구독자 없음 — 동네별 생성 생략")
        raise SystemExit(0)

    for (gx, gy), s in grids.items():
        if over_deadline(f"동네 {gx}_{gy} 이후"):
            break
        try:
            build_forecast(s["lat"], s["lon"], f"{gx}_{gy}")
        except Exception as e:
            print(f"[예측] 생성 실패(무시하고 계속): {e}")

        strikes = []
        for it in sender.fetch_lightning_data(
            s["lat"], s["lon"], sender.WATCH_RADIUS_KM, lookback_minutes=30
        ):
            try:
                strikes.append({
                    "lat": float(it["lat"]),
                    "lon": float(it["lon"]),
                    "tm": it.get("tm"),
                })
            except (TypeError, ValueError):
                continue
        build_for(gx, gy, s["lat"], s["lon"], s.get("dong"), lightning=strikes, raw=raw, stamp=stamp)
