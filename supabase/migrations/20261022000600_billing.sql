-- Stripe billing (test mode until live keys are set).
-- The stripe-webhook Edge Function calls apply_billing() with the subscription
-- state Stripe reports; that's the only path that changes a plan from billing.
-- Personal organisation -> the owner's subscriptions row (which syncs the org
-- plan and unlocks paid providers); team organisation -> organizations.plan.

create table if not exists public.org_billing (
  org_id uuid primary key references public.organizations(id) on delete cascade,
  stripe_customer_id text unique,
  stripe_subscription_id text,
  status text,                       -- Stripe subscription status
  current_period_end timestamptz,
  updated_at timestamptz not null default now()
);
alter table public.org_billing enable row level security;
create policy "org_billing_manage_read" on public.org_billing for select to authenticated using (public.org_can(org_id, 'manage'));

create or replace function public.apply_billing(
  p_org uuid, p_customer text, p_subscription text, p_status text, p_period_end timestamptz
)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  paid boolean := p_status in ('active', 'trialing', 'past_due');   -- past_due keeps access during dunning
  o public.organizations;
  owner_id uuid;
begin
  select * into o from public.organizations where id = p_org;
  if o.id is null then raise exception 'unknown organisation %', p_org; end if;

  insert into public.org_billing (org_id, stripe_customer_id, stripe_subscription_id, status, current_period_end, updated_at)
  values (p_org, p_customer, p_subscription, p_status, p_period_end, now())
  on conflict (org_id) do update set
    stripe_customer_id = coalesce(excluded.stripe_customer_id, public.org_billing.stripe_customer_id),
    stripe_subscription_id = coalesce(excluded.stripe_subscription_id, public.org_billing.stripe_subscription_id),
    status = excluded.status, current_period_end = excluded.current_period_end, updated_at = now();

  if o.personal then
    select user_id into owner_id from public.memberships where org_id = p_org and role = 'owner' limit 1;
    update public.subscriptions set status = case when paid then 'subscribed' else 'free' end, updated_at = now()
    where user_id = owner_id;
  else
    update public.organizations set plan = case when paid then 'pro' else 'free' end where id = p_org;
  end if;

  perform public.audit(p_org, 'billing.updated', 'organization', p_org::text,
    jsonb_build_object('status', p_status, 'plan', case when paid then 'pro' else 'free' end));
  return case when paid then 'pro' else 'free' end;
end;
$$;
revoke execute on function public.apply_billing(uuid, text, text, text, timestamptz) from public, anon, authenticated;
grant execute on function public.apply_billing(uuid, text, text, text, timestamptz) to service_role;
