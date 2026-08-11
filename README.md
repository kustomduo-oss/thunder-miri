# 동탄이네 천둥번개 알림이 ⚡

천둥번개가 다가오는 것을 알려주는 웹푸시 **알림** 서비스.
기상청에 관측된 낙뢰가 우리 동네로 가까워지면 폰으로 알려, 보호자가 무방비로 천둥소리를 맞지 않도록 **준비할 시간**을 확보하는 것이 목적이다.

낙뢰는 예보가 불가능하므로 이 서비스는 예측이 아니라 **이미 친 낙뢰의 접근을 감지**해 전달한다(최대 5분 지연 = 조회 주기).
공포를 치료하거나 없애주는 서비스가 **아니다.**

## 구조

| 부분 | 파일 | 호스팅 |
|------|------|--------|
| 가입 화면 (프론트) | `index.html`, `sw.js` | Netlify (정적) |
| DB (구독자 저장) | — | Supabase |
| 발송 엔진 | `sender/sender.py` | GitHub Actions (cron-job.org가 5분마다 트리거) |

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
