-- Creative fatigue (src/capabilities/fatigue.py, docs/CREATIVE_FATIGUE.md).
-- After each round's metrics, the worker checks whether an ad concept that keeps
-- reaching the same audience is losing effect: rates with real denominators,
-- a documented rule (sustained, significant, specific to the creative), and
-- near-duplicates reported apart from fatigue. A KEEP / TEST_REFRESH / RETIRE
-- recommendation can become an intervention: the next round's creative changes
-- the repeated feature (hook, visual, angle, offer framing) and still goes
-- through every check and gate. Each intervention's outcome is measured against
-- a baseline, so the organisation learns which refreshes work where.

create table if not exists public.creative_fatigue_reports (
  campaign_id uuid primary key references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  policy_version text not null,
  result jsonb not null,
  analyzed_at timestamptz not null default now()
);

create table if not exists public.creative_fatigue_alerts (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  channel text not null,
  segment text not null default 'all',  -- e.g. email variant a / b
  status text not null check (status in ('FATIGUE_SUSPECTED', 'FATIGUE_CONFIRMED')),
  recommendation text not null check (recommendation in ('TEST_REFRESH', 'RETIRE')),
  evidence jsonb not null,
  state text not null default 'open' check (state in ('open', 'refreshing', 'dismissed', 'closed')),
  decided_by uuid references auth.users (id) on delete set null,
  note text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists creative_fatigue_alerts_one_open
  on public.creative_fatigue_alerts (campaign_id, channel, segment) where state in ('open', 'refreshing');

create table if not exists public.creative_interventions (
  id uuid primary key default gen_random_uuid(),
  alert_id uuid references public.creative_fatigue_alerts (id) on delete set null,
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  channel text not null,
  segment text not null default 'all',
  domain_category text not null default 'other',
  strategy text not null check (strategy in ('NEW_HOOK', 'NEW_VISUAL', 'NEW_ANGLE', 'NEW_OFFER_FRAMING')),
  constraints jsonb not null default '{}'::jsonb,  -- what the refreshed creative must avoid
  requested_by uuid references auth.users (id) on delete set null,  -- null = proposed by the system
  applied_round integer,
  outcome text not null default 'pending' check (outcome in ('pending', 'IMPROVED', 'NO_CHANGE', 'WORSE', 'INCONCLUSIVE', 'CANCELLED')),
  outcome_detail jsonb,
  created_at timestamptz not null default now(),
  measured_at timestamptz
);
-- One refresh waiting per campaign at a time (the next round can only change once).
create unique index if not exists creative_interventions_one_pending
  on public.creative_interventions (campaign_id) where outcome = 'pending' and applied_round is null;
create index if not exists creative_interventions_learning on public.creative_interventions (org_id, channel, domain_category, strategy);

alter table public.creative_fatigue_reports enable row level security;
alter table public.creative_fatigue_alerts enable row level security;
alter table public.creative_interventions enable row level security;
do $$
declare t text;
begin
  foreach t in array array['creative_fatigue_reports', 'creative_fatigue_alerts', 'creative_interventions'] loop
    execute format('drop policy if exists %1$s_read on public.%1$s', t);
    execute format('create policy %1$s_read on public.%1$s for select to authenticated using (public.campaign_can(campaign_id, ''view''))', t);
    execute format('revoke all on public.%s from anon', t);
    execute format('revoke insert, update, delete, truncate on public.%s from authenticated', t);
    execute format('grant select on public.%s to authenticated', t);
  end loop;
end $$;

-- A person asks for (or confirms) a refresh of the fatigued creative in the next round.
create or replace function public.request_creative_refresh(p_alert uuid, p_strategy text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  a public.creative_fatigue_alerts;
  c public.campaigns;
  iid uuid;
begin
  select * into a from public.creative_fatigue_alerts where id = p_alert;
  if a.id is null then raise exception 'alert not found'; end if;
  if not (public.campaign_can(a.campaign_id, 'create') or public.campaign_can(a.campaign_id, 'manage')) then
    raise exception 'only owners, admins and marketers can refresh a creative';
  end if;
  if a.state not in ('open', 'refreshing') then raise exception 'this alert is closed'; end if;
  select * into c from public.campaigns where id = a.campaign_id;
  if c.status in ('completed', 'rejected', 'blocked') then raise exception 'the campaign has finished'; end if;
  -- Replace a refresh still waiting for the next round (system-proposed or earlier pick).
  delete from public.creative_interventions where campaign_id = a.campaign_id and outcome = 'pending' and applied_round is null;
  insert into public.creative_interventions (alert_id, campaign_id, org_id, channel, segment, domain_category, strategy, constraints, requested_by)
  values (a.id, a.campaign_id, a.org_id, a.channel, a.segment, c.domain_category, p_strategy,
          coalesce(a.evidence->'refresh_constraints', '{}'::jsonb), auth.uid())
  returning id into iid;
  update public.creative_fatigue_alerts set state = 'refreshing', decided_by = auth.uid(), updated_at = now() where id = a.id;
  perform public.audit(a.org_id, 'creative.refresh_requested', 'campaign', a.campaign_id::text,
    jsonb_build_object('alert', a.id, 'strategy', p_strategy, 'channel', a.channel, 'segment', a.segment));
  return iid;
end;
$$;
revoke execute on function public.request_creative_refresh(uuid, text) from public, anon;
grant execute on function public.request_creative_refresh(uuid, text) to authenticated;

-- Keep the creative as it is: the alert closes and any waiting refresh is cancelled.
create or replace function public.dismiss_fatigue_alert(p_alert uuid, p_note text default null)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  a public.creative_fatigue_alerts;
begin
  select * into a from public.creative_fatigue_alerts where id = p_alert;
  if a.id is null then raise exception 'alert not found'; end if;
  if not (public.campaign_can(a.campaign_id, 'create') or public.campaign_can(a.campaign_id, 'manage')) then
    raise exception 'only owners, admins and marketers can dismiss a fatigue alert';
  end if;
  update public.creative_interventions set outcome = 'CANCELLED', measured_at = now()
   where alert_id = a.id and outcome = 'pending' and applied_round is null;
  update public.creative_fatigue_alerts set state = 'dismissed', decided_by = auth.uid(), note = nullif(trim(p_note), ''), updated_at = now()
   where id = a.id;
  perform public.audit(a.org_id, 'creative.fatigue_dismissed', 'campaign', a.campaign_id::text,
    jsonb_build_object('alert', a.id, 'note', left(coalesce(p_note, ''), 300)));
end;
$$;
revoke execute on function public.dismiss_fatigue_alert(uuid, text) from public, anon;
grant execute on function public.dismiss_fatigue_alert(uuid, text) to authenticated;

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'creative_fatigue_alerts') then
    alter publication supabase_realtime add table public.creative_fatigue_alerts;
  end if;
end $$;
