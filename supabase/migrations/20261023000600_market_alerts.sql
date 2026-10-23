-- Market-moment alerts (src/scheduler/market_watch.py). Feasibility saves each
-- campaign's search keyword and its launch-time signals as a baseline; the
-- hourly sweep re-checks live campaigns about once a day and records a spike
-- (search interest or news coverage well above that baseline) as an alert.
alter table public.campaigns add column if not exists market_watch jsonb;

create table if not exists public.market_alerts (
  id bigint generated always as identity primary key,
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  kind text not null check (kind in ('trend', 'news')),
  -- {keyword, value, baseline, ratio, headline?}
  detail jsonb not null,
  created_at timestamptz not null default now(),
  dismissed_at timestamptz
);
create index if not exists market_alerts_campaign on public.market_alerts (campaign_id, created_at desc);
create index if not exists market_alerts_org on public.market_alerts (org_id, created_at desc) where dismissed_at is null;

alter table public.market_alerts enable row level security;
drop policy if exists market_alerts_read on public.market_alerts;
create policy market_alerts_read on public.market_alerts for select to authenticated
  using (public.campaign_can(campaign_id, 'view'));
-- Anyone who can see the campaign may dismiss its alerts (and change nothing else).
drop policy if exists market_alerts_dismiss on public.market_alerts;
create policy market_alerts_dismiss on public.market_alerts for update to authenticated
  using (public.campaign_can(campaign_id, 'view')) with check (public.campaign_can(campaign_id, 'view'));
revoke all on public.market_alerts from anon;
revoke insert, update, delete, truncate on public.market_alerts from authenticated;
grant select on public.market_alerts to authenticated;
grant update (dismissed_at) on public.market_alerts to authenticated;

alter publication supabase_realtime add table public.market_alerts;
