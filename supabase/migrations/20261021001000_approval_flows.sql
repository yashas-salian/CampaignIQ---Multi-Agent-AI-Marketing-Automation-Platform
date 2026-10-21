-- Approval flows: multi-approver gates, an organisation approval policy,
-- deadlines with escalation, and Slack/email notifications.
--
-- A gate is no longer decided by one UPDATE of gate_decisions. Approvers each
-- record a vote in gate_approvals; the trigger below decides the gate:
--   any 'reject'                      -> rejected
--   approvals >= required_approvals   -> approved ('edit' if any approver edited)
-- Users lose the direct UPDATE on gate_decisions, so the quorum can't be skipped.

create table if not exists public.org_settings (
  org_id uuid primary key references public.organizations(id) on delete cascade,
  required_approvals integer not null default 1 check (required_approvals between 1 and 5),
  forbid_self_approval boolean not null default false,   -- the campaign's creator can't vote on it
  approval_sla_hours integer check (approval_sla_hours between 1 and 720),
  slack_webhook_url text check (slack_webhook_url is null or slack_webhook_url like 'https://hooks.slack.com/%'),
  updated_at timestamptz not null default now()
);
alter table public.org_settings enable row level security;
-- Managers read and change the policy (the webhook URL is a credential);
-- everyone else reads the policy through org_approval_policy().
create policy "org_settings_manage_read" on public.org_settings for select to authenticated using (public.org_can(org_id, 'manage'));
create policy "org_settings_manage_insert" on public.org_settings for insert to authenticated with check (public.org_can(org_id, 'manage'));
create policy "org_settings_manage_update" on public.org_settings for update to authenticated
  using (public.org_can(org_id, 'manage')) with check (public.org_can(org_id, 'manage'));

create or replace function public.org_approval_policy(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select case when auth.uid() is null or public.org_can(p_org, 'view') then jsonb_build_object(
    'required_approvals', coalesce(s.required_approvals, 1),
    'forbid_self_approval', coalesce(s.forbid_self_approval, false),
    'approval_sla_hours', s.approval_sla_hours
  ) end
  from (select 1) one left join public.org_settings s on s.org_id = p_org;
$$;

alter table public.gate_decisions add column if not exists escalated_at timestamptz;

create table if not exists public.gate_approvals (
  gate_decision_id uuid not null references public.gate_decisions(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  decision text not null check (decision in ('approve', 'edit', 'reject')),
  comment text check (char_length(comment) <= 2000),
  created_at timestamptz not null default now(),
  primary key (gate_decision_id, user_id)
);
alter table public.gate_approvals enable row level security;

create or replace function public.gate_campaign(p_gate uuid)
returns uuid
language sql stable security definer set search_path = ''
as $$ select campaign_id from public.gate_decisions where id = p_gate; $$;

create policy "gate_approvals_read" on public.gate_approvals for select to authenticated
  using (public.campaign_can(public.gate_campaign(gate_decision_id), 'view'));
create policy "gate_approvals_vote" on public.gate_approvals for insert to authenticated
  with check (user_id = auth.uid() and public.campaign_can(public.gate_campaign(gate_decision_id), 'approve'));

-- Votes are final once cast; a gate that's decided takes no more votes.
create or replace function public.check_gate_vote()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  g public.gate_decisions;
  c public.campaigns;
  policy jsonb;
begin
  select * into g from public.gate_decisions where id = new.gate_decision_id for update;
  if g.decided_at is not null then raise exception 'this gate has already been decided'; end if;
  select * into c from public.campaigns where id = g.campaign_id;
  policy := public.org_approval_policy(c.org_id);
  if (policy->>'forbid_self_approval')::boolean and c.user_id = new.user_id then
    raise exception 'your organisation requires someone other than the campaign''s creator to approve it';
  end if;
  return new;
end; $$;
drop trigger if exists gate_approvals_check on public.gate_approvals;
create trigger gate_approvals_check before insert on public.gate_approvals
  for each row execute function public.check_gate_vote();

create or replace function public.decide_gate()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  g public.gate_decisions;
  required integer;
  approvals integer;
  any_edit boolean;
  final text;
begin
  select * into g from public.gate_decisions where id = new.gate_decision_id;
  required := (public.org_approval_policy((select org_id from public.campaigns where id = g.campaign_id))->>'required_approvals')::int;
  select count(*) filter (where decision in ('approve', 'edit')), bool_or(decision = 'edit')
    into approvals, any_edit
  from public.gate_approvals where gate_decision_id = g.id;

  if new.decision = 'reject' then
    final := 'reject';
  elsif approvals >= required then
    final := case when any_edit then 'edit' else 'approve' end;
  end if;

  if final is not null then
    update public.gate_decisions
       set decision = final, decided_at = now(),
           comment = (select string_agg(comment, E'\n' order by created_at) from public.gate_approvals
                      where gate_decision_id = g.id and comment is not null and comment <> '')
     where id = g.id;
  end if;
  return null;
end; $$;
drop trigger if exists gate_approvals_decide on public.gate_approvals;
create trigger gate_approvals_decide after insert on public.gate_approvals
  for each row execute function public.decide_gate();

-- Decisions now only come from votes.
drop policy if exists "gate_decisions_decide" on public.gate_decisions;

-- Votes are part of the audit trail.
create or replace function public.audit_gate_approvals()
returns trigger language plpgsql security definer set search_path = '' as $$
declare g public.gate_decisions;
begin
  select * into g from public.gate_decisions where id = new.gate_decision_id;
  perform public.audit((select org_id from public.campaigns where id = g.campaign_id), 'gate.vote', 'campaign',
    g.campaign_id::text, jsonb_build_object('gate', g.gate_number, 'round', g.round_number, 'vote', new.decision,
                                            'comment', left(new.comment, 500)));
  return null;
end; $$;
drop trigger if exists audit_gate_approvals on public.gate_approvals;
create trigger audit_gate_approvals after insert on public.gate_approvals
  for each row execute function public.audit_gate_approvals();

alter publication supabase_realtime add table public.gate_approvals;

-- Workers (service role, no user) need member emails to notify approvers.
create or replace function public.org_members(p_org uuid)
returns table (user_id uuid, role text, email text, username text, joined_at timestamptz)
language sql stable security definer set search_path = ''
as $$
  select m.user_id, m.role, u.email::text, u.raw_user_meta_data->>'username', m.created_at
  from public.memberships m join auth.users u on u.id = m.user_id
  where m.org_id = p_org and (auth.uid() is null or public.org_can(p_org, 'view'))
  order by m.created_at;
$$;

revoke execute on function public.gate_campaign(uuid) from public, anon;
revoke execute on function public.org_approval_policy(uuid) from public, anon;
grant execute on function public.gate_campaign(uuid), public.org_approval_policy(uuid) to authenticated, service_role;
