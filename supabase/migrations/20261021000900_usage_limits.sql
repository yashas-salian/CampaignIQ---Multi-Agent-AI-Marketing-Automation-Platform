-- Plans and usage limits per organisation.
--
-- Hard limits are enforced by triggers (no path around them); the
-- create-campaign Edge Function also checks campaign_quota_error() before it
-- dispatches a run, because the campaign row is only written after the first
-- (paid-for) LLM calls. The daily LLM token budget is soft: the worker skips an
-- organisation's runs for the rest of the day once it's spent.
-- null in a limit = unlimited.

alter table public.organizations add column if not exists plan text not null default 'free'
  check (plan in ('free', 'pro', 'enterprise'));

create table if not exists public.plan_limits (
  plan text primary key check (plan in ('free', 'pro', 'enterprise')),
  campaigns_per_day integer,
  active_campaigns integer,
  members integer,
  capability_runs_per_day integer,
  llm_tokens_per_day integer
);
insert into public.plan_limits values
  ('free', 3, 3, 5, 20, 150000),
  ('pro', 50, 25, 50, 500, 3000000),
  ('enterprise', null, null, null, null, null)
on conflict (plan) do nothing;
alter table public.plan_limits enable row level security;
create policy "plan_limits_read" on public.plan_limits for select to authenticated using (true);

-- A personal organisation follows its owner's subscription.
update public.organizations o set plan = 'pro'
from public.memberships m join public.subscriptions s on s.user_id = m.user_id
where m.org_id = o.id and o.personal and m.role = 'owner' and s.status = 'subscribed';

create or replace function public.sync_personal_plan()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  update public.organizations o set plan = case when new.status = 'subscribed' then 'pro' else 'free' end
  from public.memberships m
  where m.org_id = o.id and o.personal and m.role = 'owner' and m.user_id = new.user_id;
  return null;
end; $$;
drop trigger if exists subscriptions_sync_plan on public.subscriptions;
create trigger subscriptions_sync_plan after insert or update of status on public.subscriptions
  for each row execute function public.sync_personal_plan();

-- Plans change through billing / the admin console (service role), never by members.
create or replace function public.guard_org_plan()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.plan is distinct from old.plan and auth.uid() is not null then
    raise exception 'the plan is changed through billing, not by members';
  end if;
  return new;
end; $$;
drop trigger if exists organizations_guard_plan on public.organizations;
create trigger organizations_guard_plan before update on public.organizations
  for each row execute function public.guard_org_plan();

-- LLM usage is attributed to the organisation whose campaign made the call.
alter table public.llm_usage add column if not exists org_id uuid references public.organizations(id) on delete set null;
create index if not exists llm_usage_org_created_idx on public.llm_usage (org_id, created_at desc);

-- --- Usage readout --------------------------------------------------------

-- Internal: usage regardless of who asks (triggers and the quota checks).
create or replace function public.org_usage_unchecked(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object(
    'plan', o.plan,
    'limits', to_jsonb(l) - 'plan',
    'used', jsonb_build_object(
      'campaigns_per_day', (select count(*) from public.campaigns c where c.org_id = p_org and c.created_at > now() - interval '1 day'),
      'active_campaigns', (select count(*) from public.campaigns c where c.org_id = p_org and c.status not in ('completed', 'rejected')),
      'members', (select count(*) from public.memberships m where m.org_id = p_org),
      'llm_tokens_per_day', (select coalesce(sum(coalesce(u.prompt_tokens, 0) + coalesce(u.completion_tokens, 0)), 0)
                              from public.llm_usage u where u.org_id = p_org and u.created_at > now() - interval '1 day')
    ))
  from public.organizations o join public.plan_limits l on l.plan = o.plan
  where o.id = p_org;
$$;

-- Members' readout (Dashboard plan card); workers (no user) may ask too.
create or replace function public.org_usage(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select case when auth.uid() is null or public.org_can(p_org, 'view') then public.org_usage_unchecked(p_org) end;
$$;

-- Internal: null when another campaign may start now, else the reason it can't.
create or replace function public.campaign_quota_reason(p_org uuid)
returns text
language plpgsql stable security definer set search_path = ''
as $$
declare usage jsonb := public.org_usage_unchecked(p_org);
begin
  if usage is null then return 'organisation not found'; end if;
  if (usage->'limits'->>'campaigns_per_day') is not null
     and (usage->'used'->>'campaigns_per_day')::int >= (usage->'limits'->>'campaigns_per_day')::int then
    return format('daily campaign limit reached (%s per day on the %s plan)', usage->'limits'->>'campaigns_per_day', usage->>'plan');
  end if;
  if (usage->'limits'->>'active_campaigns') is not null
     and (usage->'used'->>'active_campaigns')::int >= (usage->'limits'->>'active_campaigns')::int then
    return format('active campaign limit reached (%s at a time on the %s plan): finish or stop one first',
                  usage->'limits'->>'active_campaigns', usage->>'plan');
  end if;
  return null;
end;
$$;

-- For the create-campaign Edge Function (caller's JWT): members only.
create or replace function public.campaign_quota_error(p_org uuid)
returns text
language sql stable security definer set search_path = ''
as $$
  select case when auth.uid() is not null and not public.org_can(p_org, 'view') then 'organisation not found'
              else public.campaign_quota_reason(p_org) end;
$$;

-- Null when the organisation may still spend LLM tokens today.
create or replace function public.token_budget_error(p_org uuid)
returns text
language plpgsql stable security definer set search_path = ''
as $$
declare usage jsonb := public.org_usage_unchecked(p_org);
begin
  if usage is not null and (usage->'limits'->>'llm_tokens_per_day') is not null
     and (usage->'used'->>'llm_tokens_per_day')::bigint >= (usage->'limits'->>'llm_tokens_per_day')::bigint then
    return format('daily AI budget used (%s tokens on the %s plan); runs resume tomorrow',
                  usage->'limits'->>'llm_tokens_per_day', usage->>'plan');
  end if;
  return null;
end;
$$;

-- --- Hard limits ----------------------------------------------------------

create or replace function public.enforce_campaign_quota()
returns trigger language plpgsql security definer set search_path = '' as $$
declare reason text := public.campaign_quota_reason(new.org_id);
begin
  if reason is not null then raise exception 'usage limit: %', reason using errcode = 'P0429'; end if;
  return new;
end; $$;
-- Runs after campaigns_default_org (trigger order is alphabetical): org_id is set.
drop trigger if exists campaigns_enforce_quota on public.campaigns;
create trigger campaigns_enforce_quota before insert on public.campaigns
  for each row execute function public.enforce_campaign_quota();

create or replace function public.enforce_member_limit()
returns trigger language plpgsql security definer set search_path = '' as $$
declare usage jsonb := public.org_usage_unchecked(new.org_id);
begin
  if (usage->'limits'->>'members') is not null and (usage->'used'->>'members')::int >= (usage->'limits'->>'members')::int then
    raise exception 'usage limit: this organisation already has % members (the % plan maximum)',
      usage->'used'->>'members', usage->>'plan' using errcode = 'P0429';
  end if;
  return new;
end; $$;
drop trigger if exists memberships_enforce_limit on public.memberships;
create trigger memberships_enforce_limit before insert on public.memberships
  for each row execute function public.enforce_member_limit();

-- Tools-page runs are per user, on the plan of their personal organisation.
create or replace function public.enforce_capability_quota()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  lim integer;
  used integer;
begin
  select l.capability_runs_per_day into lim
  from public.memberships m
  join public.organizations o on o.id = m.org_id and o.personal
  join public.plan_limits l on l.plan = o.plan
  where m.user_id = new.user_id and m.role = 'owner';
  select count(*) into used from public.capability_runs
  where user_id = new.user_id and created_at > now() - interval '1 day';
  if lim is not null and used >= lim then
    raise exception 'usage limit: % Tools runs per day on your plan', lim using errcode = 'P0429';
  end if;
  return new;
end; $$;
drop trigger if exists capability_runs_enforce_quota on public.capability_runs;
create trigger capability_runs_enforce_quota before insert on public.capability_runs
  for each row execute function public.enforce_capability_quota();

revoke execute on function public.org_usage_unchecked(uuid) from public, anon, authenticated;
revoke execute on function public.campaign_quota_reason(uuid) from public, anon, authenticated;
revoke execute on function public.org_usage(uuid) from public, anon;
revoke execute on function public.campaign_quota_error(uuid) from public, anon;
revoke execute on function public.token_budget_error(uuid) from public, anon;
grant execute on function public.org_usage(uuid), public.campaign_quota_error(uuid), public.token_budget_error(uuid)
  to authenticated, service_role;

-- The caller's personal organisation (used when no organisation is chosen).
create or replace function public.my_personal_org()
returns uuid
language sql security definer set search_path = ''
as $$
  select case when auth.uid() is not null then public.ensure_personal_org(auth.uid()) end;
$$;
revoke execute on function public.my_personal_org() from public, anon;
grant execute on function public.my_personal_org() to authenticated;
