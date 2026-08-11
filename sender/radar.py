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
CROP_KM = float(os.environ.get("RADAR_CROP_KM", "120"))   # 우리집 기준 ±거리
OUT_PX = int(os.environ.get("RADAR_OUT_PX", "700"))       # 출력 이미지 한 변

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


def fetch_radar(tm=None, tries=4):
    """레이더 합성자료(binary) 수신. 최신 파일이 아직 없을 수 있어 시각을 거슬러 재시도."""
    now = datetime.now()
    for k in range(tries):
        t = tm or (now - timedelta(minutes=15 + k * 5))
        stamp = t.replace(minute=(t.minute // 5) * 5, second=0).strftime("%Y%m%d%H%M")
        try:
            res = requests.get(RADAR_URL, params={
                "tm": stamp, "cmp": "HSR", "qcd": "KMA", "obs": "ECHO",
                "map": "HB", "disp": "B", "authKey": KMA_API_KEY,
            }, timeout=180)
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


def render(raw, lat, lon):
    """전국 격자에서 우리 동네만 잘라 PNG(투명 배경) + 위경도 범위 반환"""
    nx, ny = struct.unpack("<hh", raw[:4])
    grid = np.frombuffer(raw[4:4 + nx * ny * 2], dtype="<i2").reshape(ny, nx)

    cx, cy = _fwd.transform(lon, lat)
    i0 = int((cx - CROP_KM) / GRID_KM + nx / 2)
    i1 = int((cx + CROP_KM) / GRID_KM + nx / 2)
    j0 = int((cy - CROP_KM) / GRID_KM + ny / 2)
    j1 = int((cy + CROP_KM) / GRID_KM + ny / 2)
    i0, i1 = max(0, i0), min(nx, i1)
    j0, j1 = max(0, j0), min(ny, j1)
    sub = grid[j0:j1, i0:i1]
    if sub.size == 0:
        return None, None, 0

    # 잘라낸 영역의 실제 위경도 범위 (지도에 얹을 때 필요)
    lon0, lat0 = _inv.transform((i0 - nx / 2) * GRID_KM, (j0 - ny / 2) * GRID_KM)
    lon1, lat1 = _inv.transform((i1 - nx / 2) * GRID_KM, (j1 - ny / 2) * GRID_KM)

    dbz = sub / 100.0
    rain = sub > NO_ECHO
    rgba = np.zeros((sub.shape[0], sub.shape[1], 4), dtype=np.uint8)
    for lo, c in COLOR_STEPS:
        m = rain & (dbz >= lo)
        rgba[m] = [c[0], c[1], c[2], 200]

    img = Image.fromarray(np.flipud(rgba), "RGBA")   # 자료는 남→북 순서라 뒤집기
    img = img.resize((OUT_PX, OUT_PX), Image.NEAREST)
    bounds = {"south": lat0, "west": lon0, "north": lat1, "east": lon1}
    return img, bounds, int(rain.sum())


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


def build_for(nx_grid, ny_grid, lat, lon, dong, lightning=None, raw=None, stamp=None):
    """한 동네(기상청 격자)에 대한 레이더 이미지 + 메타 생성·업로드"""
    if raw is None:
        raw, stamp = fetch_radar()
    if raw is None:
        return None

    img, bounds, rain_cells = render(raw, lat, lon)
    if img is None:
        return None

    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    png = buf.getvalue()

    key = f"{nx_grid}_{ny_grid}"
    img_url = upload(f"{key}.png", png, "image/png")

    obs = datetime.strptime(stamp, "%Y%m%d%H%M") if stamp else datetime.now()
    meta = {
        "grid": [nx_grid, ny_grid],
        "dong": dong,
        "home": {"lat": lat, "lon": lon},
        "bounds": bounds,
        "image": img_url,
        "rain_cells": rain_cells,
        "observed_at": obs.isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "lightning": lightning or [],
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
    if not grids:
        print("[레이더] 구독자 없음 — 생성 생략")
        raise SystemExit(0)

    raw, stamp = fetch_radar()
    if raw is None:
        print("[레이더] 자료 수신 실패")
        raise SystemExit(1)

    for (gx, gy), s in grids.items():
        strikes = []
        for it in sender.fetch_lightning_data(s["lat"], s["lon"], sender.WATCH_RADIUS_KM):
            try:
                strikes.append({"lat": float(it["lat"]), "lon": float(it["lon"])})
            except (TypeError, ValueError):
                continue
        build_for(gx, gy, s["lat"], s["lon"], s.get("dong"), lightning=strikes, raw=raw, stamp=stamp)
