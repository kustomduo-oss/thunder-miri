"""오프라인 대한민국 육지/도서 필터. 관리자 텔레그램에서만 사용한다."""
import json
import math
from functools import lru_cache
from pathlib import Path
import numpy as np
from pyproj import Transformer

DATA_PATH = Path(__file__).resolve().parent / 'data' / 'south-korea-municipalities-2018.geojson'


@lru_cache(maxsize=1)
def _polygons():
    return _read_polygons(DATA_PATH)


def _read_polygons(path):
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    polygons = []
    for feature in data['features']:
        geometry = feature['geometry']
        if geometry['type'] == 'MultiPolygon':
            parts = geometry['coordinates']
        elif geometry['type'] == 'Polygon':
            parts = [geometry['coordinates']]
        else:
            raise ValueError('unsupported land geometry')
        for rings in parts:
            if not rings or any(len(ring) < 4 for ring in rings):
                raise ValueError('invalid land ring')
            xs, ys = zip(*rings[0])
            polygons.append(((min(xs), min(ys), max(xs), max(ys)), rings))
    if not polygons:
        raise ValueError('empty land boundary')
    return polygons


def _ring_location(x, y, ring):
    """0=밖, 1=안, 2=경계. GeoJSON 순서는 경도, 위도."""
    inside = False
    ax, ay = ring[-1]
    for bx, by in ring:
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) <= 1e-12 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return 2
        if (ay > y) != (by > y):
            if x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
        ax, ay = bx, by
    return int(inside)


def contains(lat, lon):
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    return _contains_polygons(lat, lon, _polygons())


def _contains_polygons(lat, lon, polygons):
    for (west, south, east, north), rings in polygons:
        if not (west <= lon <= east and south <= lat <= north):
            continue
        outer = _ring_location(lon, lat, rings[0])
        if outer == 2:
            return True
        if outer == 1 and not any(_ring_location(lon, lat, hole) == 1 for hole in rings[1:]):
            return True
    return False


@lru_cache(maxsize=1)
def _foreign_polygons():
    return [p for code in ('PRK', 'JPN', 'CHN')
            for p in _read_polygons(DATA_PATH.parent / f'exclude-{code}.geojson')]


_metric = Transformer.from_crs('EPSG:4326', 'EPSG:5179', always_xy=True)


@lru_cache(maxsize=1)
def _land_segments():
    segments = []
    for bounds, rings in _polygons():
        points = np.asarray(rings[0], dtype=float)
        x, y = _metric.transform(points[:, 0], points[:, 1])
        xy = np.column_stack((x, y))
        start, end = xy[:-1], xy[1:]
        delta = end - start
        segments.append((bounds, start, delta, (delta * delta).sum(axis=1)))
    return segments


def within_coastal_area(lat, lon, radius_km=50):
    """관리자 운영 범위: 국내 육지/도서와 그 주변 약 50km 해상.

    법적 영해 판정이 아니다. 외국 육지는 제외하며 EPSG:5179의 미터 거리로
    해안선까지 계산한다. 육지 판정은 작은 국내 섬을 우선한다.
    """
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return False
    if contains(lat, lon):
        return True
    # 넓은 전역을 처리하지 않도록 먼저 국내 경계 주변으로 한정한다.
    if not (32 <= lat <= 39.5 and 123.5 <= lon <= 133):
        return False
    if _contains_polygons(lat, lon, _foreign_polygons()):
        return False
    x, y = _metric.transform(lon, lat)
    point = np.array([x, y])
    lat_pad = radius_km / 110 + 0.02
    lon_pad = radius_km / (110 * math.cos(math.radians(lat))) + 0.02
    for (west, south, east, north), start, delta, length2 in _land_segments():
        if not (west - lon_pad <= lon <= east + lon_pad and
                south - lat_pad <= lat <= north + lat_pad):
            continue
        fraction = np.clip(((point - start) * delta).sum(axis=1) /
                           np.maximum(length2, 1e-12), 0, 1)
        offset = point - (start + fraction[:, None] * delta)
        if np.any((offset * offset).sum(axis=1) <= (radius_km * 1000) ** 2):
            return True
    return False
