# 천둥미리 ⛈️

강아지 천둥 공포 둔감화를 위한 웹푸시 알림 서비스.
기상청이 우리 동네 천둥·낙뢰·소나기를 감지하면 폰으로 미리 알려, 천둥소리를 먼저 틀어 적응시킨다.

## 구조

| 부분 | 파일 | 호스팅 |
|------|------|--------|
| 가입 화면 (프론트) | `index.html`, `sw.js` | Netlify (정적) |
| DB (구독자 저장) | — | Supabase |
| 발송 엔진 | `sender/sender.py` | GitHub Actions (10분마다) |

## 발송 엔진 실행

```bash
pip install -r sender/requirements.txt
python sender/sender.py --once    # 실제 천둥 감지 후 발송
python sender/sender.py --test    # 날씨 무관, 전 구독자에 테스트 푸시
```

## 필요한 환경변수 (GitHub Secrets)

- `SUPABASE_URL` — Supabase 프로젝트 URL
- `SUPABASE_SECRET_KEY` — Supabase secret 키 (RLS 우회, 서버 전용)
- `KMA_API_KEY` — 기상청 API허브 인증키
- `VAPID_PRIVATE_KEY` / `VAPID_PUBLIC_KEY` — 웹푸시 키 쌍
- `VAPID_SUBJECT` — `mailto:` 식별자

로컬 테스트는 `sender/.env.secret` (gitignore됨)에 같은 값들을 넣으면 된다.

## DB 스키마

`supabase_schema.sql` 참고. `subscribers` 테이블 + RLS(가입만 허용, 읽기 차단).
