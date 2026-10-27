-- A campaign appears the moment it's created. create-campaign now writes the
-- row itself (status 'created', shown as "Starting up", no feasibility score
-- yet) before it dispatches the worker; the worker fills it in at feasibility
-- instead of inserting it. A start that never gets going ends as 'failed',
-- with the reason in start_error.

alter table public.campaigns add column if not exists start_error text;

alter table public.campaigns drop constraint if exists campaigns_status_check;
alter table public.campaigns add constraint campaigns_status_check check (status in (
  'created', 'awaiting_gate_1', 'awaiting_gate_2', 'awaiting_metrics', 'awaiting_next_round', 'completed', 'rejected', 'blocked', 'failed'
));

-- A failed start never ran: it uses neither the daily allowance nor an active slot.
create or replace function public.org_usage_unchecked(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object(
    'plan', o.plan,
    'limits', to_jsonb(l) - 'plan',
    'used', jsonb_build_object(
      'campaigns_per_day', (select count(*) from public.campaigns c
                             where c.org_id = p_org and c.created_at > now() - interval '1 day' and c.status <> 'failed'),
      'active_campaigns', (select count(*) from public.campaigns c where c.org_id = p_org and c.status not in ('completed', 'rejected', 'blocked', 'failed')),
      'members', (select count(*) from public.memberships m where m.org_id = p_org),
      'llm_tokens_per_day', (select coalesce(sum(coalesce(u.prompt_tokens, 0) + coalesce(u.completion_tokens, 0)), 0)
                              from public.llm_usage u where u.org_id = p_org and u.created_at > now() - interval '1 day')
    ))
  from public.organizations o join public.plan_limits l on l.plan = o.plan
  where o.id = p_org;
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
    'active_campaigns', (select count(*) from public.campaigns where status not in ('completed', 'rejected', 'blocked', 'failed')),
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

-- The category on a just-created row is a placeholder until feasibility runs
-- (feasibility_score still null): don't put it in campaign.created, and don't
-- log the worker filling it in as a person correcting it.
create or replace function public.audit_campaigns()
returns trigger language plpgsql security definer set search_path = '' as $$
declare changes jsonb;
begin
  if tg_op = 'INSERT' then
    perform public.audit(new.org_id, 'campaign.created', 'campaign', new.id::text,
      jsonb_build_object('idea', left(new.idea, 200), 'created_by', new.user_id)
      || case when new.feasibility_score is null then '{}'::jsonb
              else jsonb_build_object('domain_category', new.domain_category) end);
  elsif tg_op = 'UPDATE' then
    changes := public.audit_changes(to_jsonb(old), to_jsonb(new),
      array['updated_at', 'campaign_summary', 'feasibility_rationale', 'current_round', 'distributed_at']);
    if changes ? 'status' then
      perform public.audit(new.org_id, 'campaign.status_changed', 'campaign', new.id::text, changes -> 'status');
    end if;
    if changes ? 'stop_requested' then
      perform public.audit(new.org_id, 'campaign.stop_requested', 'campaign', new.id::text, '{}'::jsonb);
    end if;
    if changes ? 'domain_category' and old.feasibility_score is not null then
      perform public.audit(new.org_id, 'campaign.category_corrected', 'campaign', new.id::text, changes -> 'domain_category');
    end if;
  else
    perform public.audit(old.org_id, 'campaign.deleted', 'campaign', old.id::text, jsonb_build_object('idea', left(old.idea, 200)));
  end if;
  return null;
end; $$;

-- Hourly sweep: a row create-campaign wrote whose worker never reached
-- feasibility (the run crashed, or never started) stops showing "Starting up"
-- forever. Returns how many were marked.
create or replace function public.fail_stale_campaign_starts(p_after interval default interval '45 minutes')
returns integer
language plpgsql security definer set search_path = ''
as $$
declare n integer;
begin
  update public.campaigns
     set status = 'failed',
         start_error = coalesce(start_error, 'The campaign didn''t finish starting. Please create it again.')
   where status = 'created' and feasibility_score is null and created_at < now() - p_after;
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke execute on function public.fail_stale_campaign_starts(interval) from public, anon, authenticated;
