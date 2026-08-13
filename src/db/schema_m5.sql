-- M5 schema: feedback loop + autonomy. Already applied to the live Supabase
-- project (verified live via information_schema.columns after an unrelated
-- git incident) -- this file exists to document it, not to be re-run.

alter table campaigns add column if not exists max_rounds integer;
alter table campaigns add column if not exists max_duration_minutes integer;
alter table campaigns add column if not exists campaign_summary jsonb;
alter table campaigns add column if not exists distributed_at timestamptz;
alter table campaigns add column if not exists stop_requested boolean not null default false;

create table if not exists metrics (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  round_number integer not null,
  channel text not null check (channel in ('bluesky', 'reddit', 'email')),
  raw_metrics jsonb not null,
  reward numeric not null,
  collected_at timestamptz not null default now(),
  unique (campaign_id, round_number, channel)
);
alter table metrics enable row level security;
create policy "metrics_owner" on metrics for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create table if not exists feedback (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  round_number integer not null,
  overall_reward numeric,
  stakeholder_comment text,
  revision_directive jsonb,
  continued boolean not null,
  created_at timestamptz not null default now()
);
alter table feedback enable row level security;
create policy "feedback_owner" on feedback for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
