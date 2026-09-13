"""오프라인 대한민국 육지/도서 필터. 관리자 텔레그램에서만 사용한다."""
import json
import math
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / 'data' / 'south-korea-municipalities-2018.geojson'


@lru_cache(maxsize=1)
def _polygons():
    with DATA_PATH.open(encoding='utf-8') as stream:
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
    for (west, south, east, north), rings in _polygons():
        if not (west <= lon <= east and south <= lat <= north):
            continue
        outer = _ring_location(lon, lat, rings[0])
        if outer == 2:
            return True
        if outer == 1 and not any(_ring_location(lon, lat, hole) == 1 for hole in rings[1:]):
            return True
    return False
