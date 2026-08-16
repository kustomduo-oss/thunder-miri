"""Supabase Storage의 radar 버킷에서 '과거 관측 프레임'을 세거나 지운다.

과거 프레임 파일명 규칙: {key}_{YYYYMMDDHHMM}.png   (예: 60_120_202608161200.png)
지우면 안 되는 것:
  - {key}.png / {key}.json          (최신 관측 + 메타)
  - {key}_forecast.json             (예측 메타)
  - {key}_qpf_{ef}.png              (예측 이미지)

사용법:
  python cleanup_past_frames.py          # 세기만 (기본, 안전)
  python cleanup_past_frames.py --delete # 실제 삭제
"""
import os
import re
import sys
import requests

ENV = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.secret")
if not os.path.exists(ENV):
    raise SystemExit(f"[중단] 비밀키 파일이 없습니다: {ENV}")

for line in open(ENV, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SECRET_KEY"]
BUCKET = "radar"
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

# {무엇이든}_{12자리 숫자}.png  → 과거 관측 프레임
PAST_RE = re.compile(r"^.+_\d{12}\.png$")

DELETE = "--delete" in sys.argv


def list_all():
    """버킷의 모든 파일명을 페이지 단위로 가져온다."""
    names, offset, limit = [], 0, 100
    while True:
        r = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}",
            headers={**HDR, "Content-Type": "application/json"},
            json={"prefix": "", "limit": limit, "offset": offset,
                  "sortBy": {"column": "name", "order": "asc"}},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()
        if not batch:
            break
        names += [it["name"] for it in batch]
        if len(batch) < limit:
            break
        offset += limit
    return names


files = list_all()
past = sorted(n for n in files if PAST_RE.match(n))
keep = [n for n in files if not PAST_RE.match(n)]

print(f"버킷 전체 파일: {len(files)}개")
print(f"  과거 프레임(삭제 대상): {len(past)}개")
print(f"  유지 대상            : {len(keep)}개")

if past:
    print("\n[삭제 대상 예시 최대 10개]")
    for n in past[:10]:
        print("  -", n)
    if len(past) > 10:
        print(f"  ... 외 {len(past) - 10}개")

print("\n[유지 대상 예시 최대 15개]")
for n in sorted(keep):
    print("  -", n)

if not DELETE:
    print("\n※ 세기만 했습니다. 실제로 지우려면 --delete 를 붙여 실행하세요.")
    sys.exit(0)

if not past:
    print("\n지울 것이 없습니다.")
    sys.exit(0)

print(f"\n삭제 시작 ({len(past)}개)...")
ok = fail = 0
for i in range(0, len(past), 50):
    chunk = past[i:i + 50]
    r = requests.delete(
        f"{SUPABASE_URL}/storage/v1/object/{BUCKET}",
        headers={**HDR, "Content-Type": "application/json"},
        json={"prefixes": chunk},
        timeout=60,
    )
    if r.ok:
        ok += len(chunk)
    else:
        fail += len(chunk)
        print(f"  [실패] {r.status_code} {r.text[:200]}")
    print(f"  진행 {min(i + 50, len(past))}/{len(past)}")

print(f"\n완료 · 삭제 {ok}개 · 실패 {fail}개")
