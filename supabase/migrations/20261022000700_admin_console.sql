-- Internal admin console (/admin) for platform operators.
-- Operators are listed in platform_admins (added with
-- `python -m src.admin.make_admin <email>`); org owners are not operators.
-- Every admin function checks is_platform_admin() and writes to the audit log.
-- Deliberately no impersonation: operators see aggregates and fix state,
-- they never sign in as a customer.

create table if not exists public.platform_admins (
  user_id uuid primary key references auth.users(id) on delete cascade,
  created_at timestamptz not null default now()
);
alter table public.platform_admins enable row level security;
-- No policies: only the functions below read it.

create or replace function public.is_platform_admin()
returns boolean
language sql stable security definer set search_path = ''
as $$ select exists (select 1 from public.platform_admins where user_id = auth.uid()); $$;

-- Plans change through billing (service role) or an operator, never by members.
create or replace function public.guard_org_plan()
returns trigger language plpgsql set search_path = '' as $$
begin
  if new.plan is distinct from old.plan and auth.uid() is not null and not public.is_platform_admin() then
    raise exception 'the plan is changed through billing, not by members';
  end if;
  return new;
end; $$;

create or replace function public.require_platform_admin()
returns void
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not public.is_platform_admin() then raise exception 'platform admins only'; end if;
end;
$$;

create or replace function public.admin_overview()
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
begin
  perform public.require_platform_admin();
  return jsonb_build_object(
    'users', (select count(*) from auth.users),
    'organizations', (select count(*) from public.organizations where not personal),
    'personal_orgs', (select count(*) from public.organizations where personal),
    'active_campaigns', (select count(*) from public.campaigns where status not in ('completed', 'rejected')),
    'campaigns_24h', (select count(*) from public.campaigns where created_at > now() - interval '1 day'),
    'llm_calls_24h', (select count(*) from public.llm_usage where created_at > now() - interval '1 day'),
    'llm_failures_24h', (select count(*) from public.llm_usage where created_at > now() - interval '1 day' and not ok),
    'llm_tokens_24h', (select coalesce(sum(coalesce(prompt_tokens, 0) + coalesce(completion_tokens, 0)), 0)
                       from public.llm_usage where created_at > now() - interval '1 day'),
    'dead_deliveries', (select count(*) from public.deliveries where status = 'dead'),
    'failed_webhooks', (select count(*) from public.webhook_deliveries where status = 'failed'),
    'paid_orgs', (select count(*) from public.organizations where plan <> 'free')
  );
end;
$$;

create or replace function public.admin_orgs(p_search text default '')
returns table (id uuid, name text, plan text, personal boolean, members bigint, campaigns bigint,
               tokens_24h bigint, owner_email text, created_at timestamptz)
language plpgsql stable security definer set search_path = ''
as $$
begin
  perform public.require_platform_admin();
  return query
  select o.id, o.name, o.plan, o.personal,
         (select count(*) from public.memberships m where m.org_id = o.id),
         (select count(*) from public.campaigns c where c.org_id = o.id),
         (select coalesce(sum(coalesce(u.prompt_tokens, 0) + coalesce(u.completion_tokens, 0)), 0)::bigint
            from public.llm_usage u where u.org_id = o.id and u.created_at > now() - interval '1 day'),
         (select u.email::text from public.memberships m join auth.users u on u.id = m.user_id
            where m.org_id = o.id and m.role = 'owner' order by m.created_at limit 1),
         o.created_at
  from public.organizations o
  where coalesce(p_search, '') = '' or o.name ilike '%' || p_search || '%'
     or exists (select 1 from public.memberships m join auth.users u on u.id = m.user_id
                where m.org_id = o.id and u.email ilike '%' || p_search || '%')
  order by o.created_at desc
  limit 200;
end;
$$;

create or replace function public.admin_set_plan(p_org uuid, p_plan text)
returns void
language plpgsql security definer set search_path = ''
as $$
declare old_plan text;
begin
  perform public.require_platform_admin();
  select plan into old_plan from public.organizations where id = p_org;
  update public.organizations set plan = p_plan where id = p_org;   -- guard_org_plan lets operators through
  perform public.audit(p_org, 'admin.plan_changed', 'organization', p_org::text, jsonb_build_array(old_plan, p_plan));
end;
$$;

create or replace function public.admin_dead_deliveries()
returns table (id uuid, campaign_id text, channel text, round_number integer, attempts integer, last_error text, updated_at timestamptz)
language plpgsql stable security definer set search_path = ''
as $$
begin
  perform public.require_platform_admin();
  return query select d.id, d.campaign_id, d.channel, d.round_number, d.attempts, d.last_error, d.updated_at
  from public.deliveries d where d.status = 'dead' order by d.updated_at desc limit 100;
end;
$$;

-- Give a dead send one more go (the next sweep retries it).
create or replace function public.admin_retry_delivery(p_delivery uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare d public.deliveries;
begin
  perform public.require_platform_admin();
  update public.deliveries set status = 'failed', attempts = 4, next_attempt_at = now(), updated_at = now()
  where id = p_delivery and status = 'dead' returning * into d;
  if d.id is null then raise exception 'not a dead delivery'; end if;
  perform public.audit((select org_id from public.campaigns where id::text = d.campaign_id), 'admin.delivery_retried',
    'campaign', d.campaign_id, jsonb_build_object('channel', d.channel, 'round', d.round_number));
end;
$$;

create or replace function public.admin_flags()
returns setof public.feature_flags
language plpgsql stable security definer set search_path = ''
as $$
begin
  perform public.require_platform_admin();
  return query select * from public.feature_flags order by key;
end;
$$;

create or replace function public.admin_set_flag(p_key text, p_enabled boolean, p_rollout integer, p_description text default null)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  perform public.require_platform_admin();
  insert into public.feature_flags (key, enabled, rollout_percent, description)
  values (p_key, p_enabled, p_rollout, coalesce(p_description, ''))
  on conflict (key) do update set enabled = excluded.enabled, rollout_percent = excluded.rollout_percent,
    description = coalesce(p_description, public.feature_flags.description), updated_at = now();
end;
$$;

create or replace function public.admin_verify_audit()
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
declare broken bigint;
begin
  perform public.require_platform_admin();
  broken := public.verify_audit_chain();
  return jsonb_build_object('intact', broken is null, 'first_broken_id', broken,
                            'rows', (select count(*) from public.audit_log));
end;
$$;

revoke execute on function public.admin_overview(), public.admin_orgs(text), public.admin_set_plan(uuid, text),
  public.admin_dead_deliveries(), public.admin_retry_delivery(uuid), public.admin_flags(),
  public.admin_set_flag(text, boolean, integer, text), public.admin_verify_audit(), public.require_platform_admin()
  from public, anon;
grant execute on function public.admin_overview(), public.admin_orgs(text), public.admin_set_plan(uuid, text),
  public.admin_dead_deliveries(), public.admin_retry_delivery(uuid), public.admin_flags(),
  public.admin_set_flag(text, boolean, integer, text), public.admin_verify_audit(), public.is_platform_admin()
  to authenticated;
