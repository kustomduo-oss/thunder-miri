"""읽기 전용 경로 점검. python sender/probe_kma.py [--local-env]

동일 코드를 PC/GitHub에서 실행해 비교한다. 인증키·응답 본문은 출력하지
않으며 Supabase 저장, 텔레그램, 푸시 발송 함수를 호출하지 않는다.
"""
import argparse
import json
import os
import socket
import struct
import time
from datetime import datetime, timedelta, timezone

import requests
import radar


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--local-env', action='store_true')
    args = parser.parse_args()
    if args.local_env:
        import sender
        sender.load_local_env()
    key = os.environ.get('KMA_API_KEY', '').strip()
    if not key:
        raise SystemExit('KMA_API_KEY missing; no requests made')
    now = datetime.now(timezone(timedelta(hours=9)))
    obs = now - timedelta(minutes=15)
    obs = obs.replace(minute=obs.minute // 5 * 5)
    base = now - timedelta(minutes=30)
    base = base.replace(minute=base.minute // 10 * 10)
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(
            'apihub.kma.go.kr', 443, type=socket.SOCK_STREAM)})
    except OSError as exc:
        addresses = [type(exc).__name__]
    print(json.dumps({'checked_at': now.isoformat(), 'dns': addresses,
                      'runner': os.environ.get('RUNNER_OS', 'local')}, ensure_ascii=False))
    probes = [
        ('lightning', 'https://apihub.kma.go.kr/api/typ01/url/lgt_pnt.php',
         {'tm': now.strftime('%Y%m%d%H%M'), 'itv': 15, 'lon': 127.8,
          'lat': 36.5, 'range': 500, 'gc': 'T'}, None),
        ('radar', radar.RADAR_URL,
         {'tm': obs.strftime('%Y%m%d%H%M'), 'cmp': 'HSR', 'qcd': 'KMA',
          'obs': 'ECHO', 'map': 'HB', 'disp': 'B'}, radar.validate_radar),
        ('qpf', radar.QPF_URL,
         {'eva': 2, 'tm': base.strftime('%Y%m%d%H%M'), 'qpf': 'B', 'ef': 60,
          'map': 'HB', 'grid': 2, 'legend': 0, 'size': 600,
          'zoom_level': 0, 'zoom_x': 0, 'zoom_y': 0},
         lambda raw: radar.validate_png(raw, 'HB')),
    ]
    for name, url, params, validator in probes:
        started = time.monotonic()
        result = {'endpoint': name, 'tm': params['tm']}
        try:
            with requests.get(url, params={**params, 'authKey': key},
                              timeout=(10, 20)) as response:
                result.update(http=response.status_code, bytes=len(response.content))
                if name == 'radar' and len(response.content) >= 4:
                    nx, ny = struct.unpack('<hh', response.content[:4])
                    result.update(dimensions=[nx, ny], expected_bytes=4 + nx * ny * 2,
                                  content_length=response.headers.get('Content-Length'),
                                  content_type=response.headers.get('Content-Type'))
                response.raise_for_status()
                if validator:
                    validator(response.content)
                    result['payload_valid'] = True
                result['result'] = 'response_received'
        except Exception as exc:
            result['result'] = type(exc).__name__
        result['seconds'] = round(time.monotonic() - started, 2)
        print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
