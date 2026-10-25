-- Proof-of-impact experiments (src/capabilities/impact.py, docs/PROOF_OF_IMPACT.md).
-- A campaign's email audience can be run as a pre-registered randomized
-- experiment: a holdout control group that gets nothing, against the people
-- who get the campaign (optionally split into A and B). The design (hypothesis,
-- primary metric, split, attribution window, stopping rule) is declared before
-- the first send and locked once it starts. Assignment is a stable hash of the
-- experiment and the address, stored on first use, so a retry or a resumed run
-- never moves anyone. Outcomes (exposures, clicks, conversions) are timestamped
-- events with their source; the worker analyses them and stores the result.

create table if not exists public.experiments (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null unique references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  hypothesis text not null check (char_length(hypothesis) between 10 and 1000),
  primary_metric text not null check (primary_metric in ('qualified_signup_rate', 'conversion_rate', 'click_through_rate')),
  -- holdout: control vs treatment; holdout_ab: control vs treatment A+B (and B vs A); ab: B vs A, no control.
  design text not null check (design in ('holdout', 'holdout_ab', 'ab')),
  assignment_unit text not null default 'email_recipient' check (assignment_unit = 'email_recipient'),
  control_share numeric not null default 0 check (control_share >= 0 and control_share <= 0.5),
  attribution_window_days integer not null default 7 check (attribution_window_days between 1 and 30),
  duration_days integer not null default 14 check (duration_days between 1 and 90),
  min_units_per_arm integer not null default 100 check (min_units_per_arm between 10 and 1000000),
  min_effect numeric not null default 0.01 check (min_effect > 0 and min_effect < 1),  -- smallest absolute lift worth acting on
  baseline_rate numeric check (baseline_rate is null or (baseline_rate > 0 and baseline_rate < 1)),  -- expected control rate (planning only)
  policy_version text not null default 'impact-v1',
  status text not null default 'declared' check (status in ('declared', 'running', 'completed')),
  started_at timestamptz,
  ends_at timestamptz,       -- the exposure period ends (started_at + duration, or when the campaign finishes)
  analysis_at timestamptz,  -- ends_at + the attribution window: the predeclared moment of the final analysis
  result jsonb,
  result_status text,
  analyzed_at timestamptz,
  concluded_at timestamptz,
  bandit_fed_at timestamptz,
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- A control group never gets a link, so it can't click: comparing click rates against it means nothing.
  constraint experiments_metric_fits_design check (design = 'ab' or primary_metric <> 'click_through_rate'),
  constraint experiments_control_fits_design check ((design = 'ab') = (control_share = 0))
);
create index if not exists experiments_running on public.experiments (status) where status = 'running';

create table if not exists public.experiment_assignments (
  id uuid primary key default gen_random_uuid(),
  experiment_id uuid not null references public.experiments (id) on delete cascade,
  unit_hash text not null,  -- sha256(experiment id : normalised address); the address itself isn't stored here
  arm text not null check (arm in ('control', 'treatment', 'treatment_b')),
  token text not null unique default encode(extensions.gen_random_bytes(16), 'hex'),  -- carried in the unit's links
  assigned_at timestamptz not null default now(),
  unique (experiment_id, unit_hash)
);

create table if not exists public.experiment_events (
  id bigint generated always as identity primary key,
  experiment_id uuid not null references public.experiments (id) on delete cascade,
  assignment_id uuid references public.experiment_assignments (id) on delete cascade,  -- null: a conversion nobody in the experiment matched
  arm text,
  kind text not null check (kind in ('exposure', 'click', 'conversion')),
  qualified boolean not null default false,
  value numeric check (value is null or value >= 0),
  currency text check (currency is null or currency ~ '^[A-Z]{3}$'),
  round_number integer,
  source text not null check (source in ('email_send', 'track_click', 'conversion_api')),
  external_id text not null,  -- de-duplication key (a retried postback counts once)
  occurred_at timestamptz not null,
  received_at timestamptz not null default now(),
  unique (experiment_id, kind, external_id)
);
create index if not exists experiment_events_by_experiment on public.experiment_events (experiment_id, kind);

-- Members read the experiment and its stored result; assignments (tokens) and
-- raw events are for the workers only.
alter table public.experiments enable row level security;
alter table public.experiment_assignments enable row level security;
alter table public.experiment_events enable row level security;
drop policy if exists experiments_read on public.experiments;
create policy experiments_read on public.experiments for select to authenticated
  using (public.campaign_can(campaign_id, 'view'));
revoke all on public.experiments from anon;
revoke insert, update, delete, truncate on public.experiments from authenticated;
grant select on public.experiments to authenticated;
revoke all on public.experiment_assignments from anon, authenticated;
revoke all on public.experiment_events from anon, authenticated;

-- Pre-registration: once an experiment has started, its design can't change.
create or replace function public.experiments_lock_design()
returns trigger
language plpgsql set search_path = ''
as $$
begin
  if old.started_at is not null and (
       new.hypothesis is distinct from old.hypothesis or new.primary_metric is distinct from old.primary_metric
    or new.design is distinct from old.design or new.control_share is distinct from old.control_share
    or new.attribution_window_days is distinct from old.attribution_window_days
    or new.duration_days is distinct from old.duration_days or new.min_units_per_arm is distinct from old.min_units_per_arm
    or new.min_effect is distinct from old.min_effect or new.policy_version is distinct from old.policy_version
    or new.started_at is distinct from old.started_at) then
    raise exception 'the experiment has started: its design is locked';
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists experiments_lock_design on public.experiments;
create trigger experiments_lock_design before update on public.experiments
  for each row execute function public.experiments_lock_design();

-- Declare (or, before it starts, change) the campaign's experiment.
create or replace function public.declare_experiment(
  p_campaign uuid, p_hypothesis text, p_metric text, p_control_share numeric,
  p_window_days integer default 7, p_duration_days integer default 14, p_min_units integer default 100,
  p_min_effect numeric default 0.01, p_baseline numeric default null
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  c public.campaigns;
  e public.experiments;
  v_design text;
begin
  if not (public.campaign_can(p_campaign, 'create') or public.campaign_can(p_campaign, 'manage')) then
    raise exception 'not allowed to change this campaign';
  end if;
  select * into c from public.campaigns where id = p_campaign for update;
  if coalesce(array_length(c.email_to, 1), 0) = 0 then
    raise exception 'an experiment needs an email audience to randomise';
  end if;
  if c.status in ('completed', 'rejected', 'blocked') then
    raise exception 'the campaign has finished';
  end if;
  select * into e from public.experiments where campaign_id = p_campaign;
  if e.started_at is not null then
    raise exception 'the experiment has started: its design is locked';
  end if;
  if exists (select 1 from public.deliveries where campaign_id = p_campaign::text and channel in ('email', 'email_b')
              and status in ('sent', 'sending')) then
    raise exception 'emails already went out without the experiment: declare it before the first send';
  end if;
  v_design := case when coalesce(p_control_share, 0) = 0 then 'ab'
                   when c.ab_test then 'holdout_ab' else 'holdout' end;
  if v_design = 'ab' and not c.ab_test then
    raise exception 'without a control group the experiment compares A and B: turn on the A/B test or keep a control group';
  end if;
  insert into public.experiments (campaign_id, org_id, hypothesis, primary_metric, design, control_share,
                                  attribution_window_days, duration_days, min_units_per_arm, min_effect, baseline_rate, created_by)
  values (p_campaign, c.org_id, trim(p_hypothesis), p_metric, v_design, coalesce(p_control_share, 0),
          p_window_days, p_duration_days, p_min_units, p_min_effect, p_baseline, auth.uid())
  on conflict (campaign_id) do update set
    hypothesis = excluded.hypothesis, primary_metric = excluded.primary_metric, design = excluded.design,
    control_share = excluded.control_share, attribution_window_days = excluded.attribution_window_days,
    duration_days = excluded.duration_days, min_units_per_arm = excluded.min_units_per_arm,
    min_effect = excluded.min_effect, baseline_rate = excluded.baseline_rate
  returning * into e;
  perform public.audit(c.org_id, 'experiment.declared', 'campaign', p_campaign::text,
    jsonb_build_object('experiment', e.id, 'metric', e.primary_metric, 'design', e.design, 'control_share', e.control_share,
                       'hypothesis', left(e.hypothesis, 300)));
  return e.id;
end;
$$;
revoke execute on function public.declare_experiment(uuid, text, text, numeric, integer, integer, integer, numeric, numeric) from public, anon;
grant execute on function public.declare_experiment(uuid, text, text, numeric, integer, integer, integer, numeric, numeric) to authenticated;

-- Withdraw an experiment that hasn't started.
create or replace function public.withdraw_experiment(p_campaign uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  e public.experiments;
begin
  if not (public.campaign_can(p_campaign, 'create') or public.campaign_can(p_campaign, 'manage')) then
    raise exception 'not allowed to change this campaign';
  end if;
  select * into e from public.experiments where campaign_id = p_campaign;
  if e.id is null then return; end if;
  if e.started_at is not null then
    raise exception 'the experiment has started: it runs to its predeclared end';
  end if;
  delete from public.experiments where id = e.id;
  perform public.audit(e.org_id, 'experiment.withdrawn', 'campaign', p_campaign::text, jsonb_build_object('experiment', e.id));
end;
$$;
revoke execute on function public.withdraw_experiment(uuid) from public, anon;
grant execute on function public.withdraw_experiment(uuid) to authenticated;

-- The first send starts the experiment and stores the assignments. Later calls
-- (a retry, the next round, a new address) only add units that are new: an
-- existing unit keeps its arm. Returns how many units the experiment has (the
-- caller reads them page by page: an API response is capped at 1000 rows).
drop function if exists public.start_experiment(uuid, jsonb);
create or replace function public.start_experiment(p_experiment uuid, p_units jsonb)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  e public.experiments;
begin
  select * into e from public.experiments where id = p_experiment for update;
  if e.id is null then raise exception 'experiment not found'; end if;
  if e.started_at is null then
    update public.experiments
       set status = 'running', started_at = now(), ends_at = now() + make_interval(days => e.duration_days),
           analysis_at = now() + make_interval(days => e.duration_days + e.attribution_window_days)
     where id = p_experiment;
    perform public.audit(e.org_id, 'experiment.started', 'campaign', e.campaign_id::text,
      jsonb_build_object('experiment', e.id, 'units', jsonb_array_length(coalesce(p_units, '[]'::jsonb))));
  end if;
  insert into public.experiment_assignments (experiment_id, unit_hash, arm)
  select p_experiment, u->>'unit_hash', u->>'arm' from jsonb_array_elements(coalesce(p_units, '[]'::jsonb)) u
  on conflict (experiment_id, unit_hash) do nothing;
  return (select count(*) from public.experiment_assignments a where a.experiment_id = p_experiment);
end;
$$;
revoke execute on function public.start_experiment(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.start_experiment(uuid, jsonb) to service_role;

-- Sent emails: one exposure per unit and round.
create or replace function public.record_exposures(p_experiment uuid, p_round integer, p_unit_hashes text[])
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  n integer;
begin
  insert into public.experiment_events (experiment_id, assignment_id, arm, kind, round_number, source, external_id, occurred_at)
  select p_experiment, a.id, a.arm, 'exposure', p_round, 'email_send', format('%s:%s', p_round, a.unit_hash), now()
    from public.experiment_assignments a
   where a.experiment_id = p_experiment and a.unit_hash = any (p_unit_hashes)
  on conflict (experiment_id, kind, external_id) do nothing;
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke execute on function public.record_exposures(uuid, integer, text[]) from public, anon, authenticated;
grant execute on function public.record_exposures(uuid, integer, text[]) to service_role;

-- A tracked link was followed (track-click). Returns the token's arm, or null.
create or replace function public.record_click(p_token text, p_round integer)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  a public.experiment_assignments;
begin
  select * into a from public.experiment_assignments where token = p_token;
  if a.id is null then return null; end if;
  insert into public.experiment_events (experiment_id, assignment_id, arm, kind, round_number, source, external_id, occurred_at)
  values (a.experiment_id, a.id, a.arm, 'click', p_round, 'track_click', gen_random_uuid()::text, now());
  return a.arm;
end;
$$;
revoke execute on function public.record_click(text, integer) from public, anon, authenticated;
grant execute on function public.record_click(text, integer) to service_role;

-- A conversion reported by the brand's site (API POST /v1/conversions), matched
-- by the link token or by the hashed address (the only way a control unit, who
-- never got a link, can be matched). Retries with the same event id count once.
create or replace function public.record_conversion(
  p_experiment uuid, p_external_id text, p_occurred_at timestamptz, p_token text default null,
  p_unit_hash text default null, p_qualified boolean default false, p_value numeric default null, p_currency text default null
)
returns table (matched boolean, arm text, duplicate boolean)
language plpgsql security definer set search_path = ''
as $$
declare
  a public.experiment_assignments;
  inserted integer;
begin
  if p_token is not null then
    select * into a from public.experiment_assignments where token = p_token and experiment_id = p_experiment;
  end if;
  if a.id is null and p_unit_hash is not null then
    select * into a from public.experiment_assignments where unit_hash = p_unit_hash and experiment_id = p_experiment;
  end if;
  insert into public.experiment_events (experiment_id, assignment_id, arm, kind, qualified, value, currency, source, external_id, occurred_at)
  values (p_experiment, a.id, a.arm, 'conversion', coalesce(p_qualified, false), p_value, upper(p_currency),
          'conversion_api', left(p_external_id, 200), p_occurred_at)
  on conflict (experiment_id, kind, external_id) do nothing;
  get diagnostics inserted = row_count;
  return query select a.id is not null, a.arm, inserted = 0;
end;
$$;
revoke execute on function public.record_conversion(uuid, text, timestamptz, text, text, boolean, numeric, text) from public, anon, authenticated;
grant execute on function public.record_conversion(uuid, text, timestamptz, text, text, boolean, numeric, text) to service_role;

-- The worker stores each analysis; the final one (at analysis_at) concludes the experiment, once.
create or replace function public.save_impact(p_experiment uuid, p_result jsonb, p_status text, p_final boolean,
                                              p_ends_at timestamptz default null)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  e public.experiments;
begin
  select * into e from public.experiments where id = p_experiment for update;
  if e.id is null then raise exception 'experiment not found'; end if;
  if e.status = 'completed' then return; end if;  -- the final result is never overwritten
  if p_ends_at is not null and p_ends_at < e.ends_at then  -- the campaign finished early: the window starts closing now
    update public.experiments set ends_at = p_ends_at,
           analysis_at = p_ends_at + make_interval(days => e.attribution_window_days)
     where id = p_experiment;
  end if;
  update public.experiments
     set result = p_result, result_status = p_status, analyzed_at = now(),
         status = case when p_final then 'completed' else status end,
         concluded_at = case when p_final then now() else concluded_at end
   where id = p_experiment;
  if p_final then
    perform public.audit(e.org_id, 'experiment.concluded', 'campaign', e.campaign_id::text,
      jsonb_build_object('experiment', e.id, 'status', p_status, 'reason', p_result->>'reason',
                         'absolute_lift', p_result->'estimate'->'absolute_lift', 'interval', p_result->'estimate'->'interval'));
  end if;
end;
$$;
revoke execute on function public.save_impact(uuid, jsonb, text, boolean, timestamptz) from public, anon, authenticated;
grant execute on function public.save_impact(uuid, jsonb, text, boolean, timestamptz) to service_role;

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'experiments') then
    alter publication supabase_realtime add table public.experiments;
  end if;
end $$;
