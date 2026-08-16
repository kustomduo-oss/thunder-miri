-- 썬더미리 — 구독자 테이블 (thunder-miri 프로젝트에 적용 완료)
-- Supabase 대시보드 > SQL Editor 에 붙여넣고 RUN

create table if not exists subscribers (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  dog_name         text,
  lat              double precision not null,
  lon              double precision not null,
  nx               integer not null,          -- 기상청 격자 X
  ny               integer not null,          -- 기상청 격자 Y
  dong             text,                      -- 동네 이름 (표시용)
  subscription     jsonb,                     -- 웹푸시 구독 객체 (3단계에서 채워짐)
  active           boolean not null default true,
  last_notified_at timestamptz,               -- 강수예보 중복 방지용
  cooldown_min     integer not null default 30, -- 이전 알림 정책 호환용(현재 낙뢰 발송에서는 사용하지 않음)
  last_lightning_at    timestamptz,             -- 낙뢰 경보 시각(강수와 별도 추적)
  last_lightning_level text                     -- 마지막 낙뢰 단계: watch(30~50km)/warning(30km 이내)
);

-- 이미 테이블이 있는 경우 칸만 추가 (운영 DB에 적용 완료)
alter table subscribers add column if not exists cooldown_min integer not null default 30;
alter table subscribers add column if not exists last_lightning_at timestamptz;
alter table subscribers add column if not exists last_lightning_level text;

-- 같은 격자끼리 묶어 조회할 때 빠르게
create index if not exists idx_subscribers_grid on subscribers (nx, ny) where active;

-- 보안: RLS 켜기
alter table subscribers enable row level security;

-- 가입(INSERT)만 모두에게 허용. SELECT 정책은 없음 → 남의 데이터 읽기/수정 불가.
-- (특정 role 'anon' 대신 public 으로 둬야 새 publishable 키와 호환됨)
create policy "anyone can subscribe"
  on subscribers for insert
  to public
  with check (true);


-- ----------------------------------------------------------------
-- 2026-08-16 추가: 한반도 밖 좌표 저장 거부
-- ----------------------------------------------------------------
-- 왜: publishable 키가 JS에 공개돼 있어 누구나 행을 넣을 수 있다.
--     발송·레이더 엔진은 '격자(nx,ny) 단위'로 일하므로, 격자를 넓게 흩뿌리면
--     기상청 API 호출과 이미지 생성이 격자 수에 비례해 폭증한다.
--     좌표를 한반도로 묶으면 뿌릴 수 있는 범위가 크게 줄어든다.
--
-- 범위 근거: 마라도 33.06N / 백령도 37.9N·124.6E / 독도 131.87E 를 모두 포함
-- 기존 행은 재검사되지 않으므로 영향 없음 (with check 는 INSERT에만 적용)
--
-- ⚠️ drop 과 create 사이에 가입이 막히는 틈이 생기므로 반드시 한 트랜잭션으로 실행할 것.
-- ⚠️ 적용 후 사이트에서 실제로 가입이 되는지 반드시 테스트할 것.

begin;

drop policy if exists "anyone can subscribe" on subscribers;

create policy "anyone can subscribe"
  on subscribers for insert
  to public
  with check (
    lat between 33 and 39
    and lon between 124 and 132
  );

commit;

grant insert on subscribers to anon, authenticated;

-- 주의: 브라우저에서 저장할 때 'Prefer: return=representation'(되읽기) 헤더를 쓰면
--       SELECT 정책이 없어 RLS 위반이 난다. apikey 헤더만 쓰고 되읽기는 하지 말 것.
-- (발송 엔진은 service_role/secret 키로 RLS를 우회해 전체를 읽음 — 4단계)
