-- Decision intelligence (src/capabilities/decision.py): before any creative is
-- made, the engine recommends LAUNCH / TEST_SMALL / WAIT / KILL /
-- INSUFFICIENT_EVIDENCE from the evidence gathered so far. Every decision is
-- kept with its inputs snapshot and policy version (reproducible, auditable),
-- re-evaluations add rows (trigger 'reevaluation'), and the campaign's
-- eventual outcome is written back to its latest decision at the end.
create table if not exists public.campaign_decisions (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  trigger text not null default 'initial' check (trigger in ('initial', 'reevaluation')),
  decision text not null check (decision in ('LAUNCH', 'TEST_SMALL', 'WAIT', 'KILL', 'INSUFFICIENT_EVIDENCE')),
  opportunity_score integer check (opportunity_score between 0 and 100),
  uncertainty numeric not null check (uncertainty between 0 and 1),
  reason_codes text[] not null default '{}',
  factors jsonb not null default '[]'::jsonb,
  hard_blocks jsonb not null default '[]'::jsonb,
  review_flags jsonb not null default '[]'::jsonb,
  constraints jsonb not null default '{}'::jsonb,
  reevaluate jsonb,
  baseline jsonb not null default '{}'::jsonb,
  policy_version text not null,
  inputs jsonb not null default '{}'::jsonb,
  outcome jsonb,
  created_at timestamptz not null default now()
);
create index if not exists campaign_decisions_campaign on public.campaign_decisions (campaign_id, created_at desc);

alter table public.campaign_decisions enable row level security;
drop policy if exists campaign_decisions_read on public.campaign_decisions;
create policy campaign_decisions_read on public.campaign_decisions for select to authenticated
  using (public.campaign_can(campaign_id, 'view'));
-- Written only by the worker (service role): people can read, never edit.
revoke all on public.campaign_decisions from anon;
revoke insert, update, delete, truncate on public.campaign_decisions from authenticated;
grant select on public.campaign_decisions to authenticated;

-- Every recommendation lands in the audit log.
create or replace function public.audit_campaign_decisions()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.audit(new.org_id, 'campaign.decision', 'campaign', new.campaign_id::text,
    jsonb_build_object('decision', new.decision, 'score', new.opportunity_score, 'trigger', new.trigger,
                       'reasons', to_jsonb(new.reason_codes), 'policy', new.policy_version));
  return null;
end; $$;
drop trigger if exists audit_campaign_decisions on public.campaign_decisions;
create trigger audit_campaign_decisions after insert on public.campaign_decisions
  for each row execute function public.audit_campaign_decisions();

-- A hard block (prohibited product, banned word, claim that can't be
-- substantiated, broken link) stops a campaign before Gate 1: status 'blocked'.
alter table public.campaigns drop constraint if exists campaigns_status_check;
alter table public.campaigns add constraint campaigns_status_check check (status in (
  'created', 'awaiting_gate_1', 'awaiting_gate_2', 'awaiting_metrics', 'awaiting_next_round', 'completed', 'rejected', 'blocked'
));

alter publication supabase_realtime add table public.campaign_decisions;

-- A blocked campaign is finished: it doesn't count against the plan's active-campaign limit.
create or replace function public.org_usage_unchecked(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object(
    'plan', o.plan,
    'limits', to_jsonb(l) - 'plan',
    'used', jsonb_build_object(
      'campaigns_per_day', (select count(*) from public.campaigns c where c.org_id = p_org and c.created_at > now() - interval '1 day'),
      'active_campaigns', (select count(*) from public.campaigns c where c.org_id = p_org and c.status not in ('completed', 'rejected', 'blocked')),
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
    'active_campaigns', (select count(*) from public.campaigns where status not in ('completed', 'rejected', 'blocked')),
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

-- Gate 1 against the engine's advice: approving a campaign it recommended to
-- KILL, WAIT on or couldn't judge (INSUFFICIENT_EVIDENCE) needs a written
-- reason (kept with the vote and in the audit log). A hard block can never be
-- approved. Enforced here, so no client can skip it.
create or replace function public.check_decision_override()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  g public.gate_decisions;
  d public.campaign_decisions;
begin
  if new.decision not in ('approve', 'edit') then return new; end if;
  select * into g from public.gate_decisions where id = new.gate_decision_id;
  if g.gate_number <> 1 then return new; end if;
  select * into d from public.campaign_decisions where campaign_id = g.campaign_id order by created_at desc limit 1;
  if d.id is null then return new; end if;
  if jsonb_array_length(d.hard_blocks) > 0 then
    raise exception 'this campaign is blocked (%): it can''t be approved', d.reason_codes[1];
  end if;
  if d.decision in ('KILL', 'WAIT', 'INSUFFICIENT_EVIDENCE') and char_length(trim(coalesce(new.comment, ''))) < 10 then
    raise exception 'the decision engine recommended % for this campaign: approving it anyway needs a reason (at least 10 characters)', d.decision;
  end if;
  return new;
end; $$;
drop trigger if exists gate_approvals_decision_override on public.gate_approvals;
create trigger gate_approvals_decision_override before insert on public.gate_approvals
  for each row execute function public.check_decision_override();
