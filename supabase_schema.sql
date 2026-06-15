-- 번개 추적기 — 구독자 테이블 (thunder-miri 프로젝트에 적용 완료)
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
  last_notified_at timestamptz                -- 중복 알림 방지용
);

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

grant insert on subscribers to anon, authenticated;

-- 주의: 브라우저에서 저장할 때 'Prefer: return=representation'(되읽기) 헤더를 쓰면
--       SELECT 정책이 없어 RLS 위반이 난다. apikey 헤더만 쓰고 되읽기는 하지 말 것.
-- (발송 엔진은 service_role/secret 키로 RLS를 우회해 전체를 읽음 — 4단계)
