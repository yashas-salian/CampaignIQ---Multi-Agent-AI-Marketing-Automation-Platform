-- Campaign crash test (src/capabilities/crash_test.py): before Gate 2 the ad
-- is checked by deterministic rules (FTC/Meta-grounded) and a versioned set of
-- simulated scenarios, then revised and re-tested when something is high or
-- critical. Each run is kept whole (report), with the original and revised
-- results side by side; applying the revision at the gate is recorded too.
create table if not exists public.crash_tests (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  user_id uuid references auth.users (id) on delete set null,
  round_number integer not null,
  trigger text not null default 'pipeline' check (trigger in ('pipeline', 'rerun')),
  scenario_set text not null,
  rules_version text not null,
  status text not null check (status in ('COMPLETED', 'RULES_ONLY')),
  risk text not null check (risk in ('clear', 'low', 'medium', 'high', 'critical')),
  revised_risk text check (revised_risk in ('clear', 'low', 'medium', 'high', 'critical')),
  report jsonb not null,
  applied_at timestamptz,
  applied_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now()
);
create index if not exists crash_tests_round on public.crash_tests (campaign_id, round_number, created_at desc);

alter table public.crash_tests enable row level security;
drop policy if exists crash_tests_read on public.crash_tests;
create policy crash_tests_read on public.crash_tests for select to authenticated
  using (public.campaign_can(campaign_id, 'view'));
-- Written only by the worker (service role).
revoke all on public.crash_tests from anon;
revoke insert, update, delete, truncate on public.crash_tests from authenticated;
grant select on public.crash_tests to authenticated;

create or replace function public.audit_crash_tests()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    perform public.audit(new.org_id, 'campaign.crash_test', 'campaign', new.campaign_id::text,
      jsonb_build_object('round', new.round_number, 'risk', new.risk, 'revised_risk', new.revised_risk,
                         'scenario_set', new.scenario_set, 'trigger', new.trigger));
  elsif old.applied_at is null and new.applied_at is not null then
    perform public.audit(new.org_id, 'campaign.crash_test_applied', 'campaign', new.campaign_id::text,
      jsonb_build_object('round', new.round_number, 'risk', new.risk, 'revised_risk', new.revised_risk));
  end if;
  return null;
end; $$;
drop trigger if exists audit_crash_tests on public.crash_tests;
create trigger audit_crash_tests after insert or update on public.crash_tests
  for each row execute function public.audit_crash_tests();

-- The risk that applies to the copy now at the gate: the revision's once it's applied.
create or replace function public.crash_test_risk(p_campaign uuid, p_round integer)
returns text
language sql stable security definer set search_path = ''
as $$
  select case when c.applied_at is not null then c.revised_risk else c.risk end
  from public.crash_tests c where c.campaign_id = p_campaign and c.round_number = p_round
  order by c.created_at desc limit 1;
$$;
revoke execute on function public.crash_test_risk(uuid, integer) from public, anon;
grant execute on function public.crash_test_risk(uuid, integer) to authenticated, service_role;

-- Critical findings go to the people at Gate 2, never past them: approving an
-- ad whose current crash test is critical needs a written reason.
create or replace function public.check_crash_test_override()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  g public.gate_decisions;
begin
  if new.decision not in ('approve', 'edit') then return new; end if;
  select * into g from public.gate_decisions where id = new.gate_decision_id;
  if g.gate_number <> 2 then return new; end if;
  if public.crash_test_risk(g.campaign_id, g.round_number) = 'critical'
     and char_length(trim(coalesce(new.comment, ''))) < 10 then
    raise exception 'the crash test found a critical problem in this ad: approving it anyway needs a reason (at least 10 characters)';
  end if;
  return new;
end; $$;
drop trigger if exists gate_approvals_crash_test_override on public.gate_approvals;
create trigger gate_approvals_crash_test_override before insert on public.gate_approvals
  for each row execute function public.check_crash_test_override();

alter publication supabase_realtime add table public.crash_tests;
