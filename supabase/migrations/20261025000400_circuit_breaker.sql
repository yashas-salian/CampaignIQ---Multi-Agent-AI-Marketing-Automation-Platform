-- Brand reputation circuit breaker (src/capabilities/circuit_breaker.py).
-- A live campaign is paused, whole or per channel, the moment something makes
-- it unsafe to keep publishing: an expired offer, a broken link, copy that now
-- breaks a hard rule, an approval that no longer stands, a verified brand-risk
-- signal, or a person pulling the emergency stop. While a critical hold is
-- active, claim_delivery() refuses every send (atomically: a worker can't slip
-- past a pause on stale state), the sweep doesn't advance the campaign, and
-- only an owner or admin can resume it, with a written note.

-- When the campaign's offer ends (optional; set on the campaign page).
alter table public.campaigns add column if not exists offer_ends_at timestamptz;
-- Set while at least one critical hold is active (kept in step by the functions below).
alter table public.campaigns add column if not exists paused_at timestamptz;

create table if not exists public.campaign_holds (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.campaigns (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  channel text check (channel is null or channel in ('bluesky', 'mastodon', 'reddit', 'email')),  -- null = every channel
  trigger text not null check (trigger in (
    'EXPIRED_OFFER', 'INVALID_DESTINATION', 'POLICY_VIOLATION', 'REVOKED_APPROVAL', 'BRAND_RISK', 'MANUAL_STOP')),
  severity text not null check (severity in ('critical', 'warning')),  -- critical pauses; warning only notifies
  status text not null default 'active' check (status in ('active', 'resolved', 'false_alarm')),
  detail text not null,
  evidence jsonb not null default '{}'::jsonb,
  signal_at timestamptz,  -- when the evidence was observed
  created_by uuid references auth.users (id) on delete set null,  -- null = the system
  created_at timestamptz not null default now(),
  resolved_at timestamptz,
  resolved_by uuid references auth.users (id) on delete set null,
  resolution_note text
);
-- One active hold per trigger and channel: a re-check of the same condition doesn't stack holds.
create unique index if not exists campaign_holds_one_active
  on public.campaign_holds (campaign_id, trigger, coalesce(channel, '*')) where status = 'active';
create index if not exists campaign_holds_campaign on public.campaign_holds (campaign_id, created_at desc);

alter table public.campaign_holds enable row level security;
drop policy if exists campaign_holds_read on public.campaign_holds;
create policy campaign_holds_read on public.campaign_holds for select to authenticated
  using (public.campaign_can(campaign_id, 'view'));
-- Changed only through the functions below.
revoke all on public.campaign_holds from anon;
revoke insert, update, delete, truncate on public.campaign_holds from authenticated;
grant select on public.campaign_holds to authenticated;

-- Held sends wait here until the hold is resolved, then go back to the retry queue.
alter table public.deliveries drop constraint if exists deliveries_status_check;
alter table public.deliveries add constraint deliveries_status_check
  check (status in ('pending', 'sending', 'sent', 'dry_run', 'failed', 'dead', 'held'));

-- The single writer for holds. Locks the campaign row first, the same order as
-- claim_delivery(), so a pause and a send can't interleave.
create or replace function public.place_hold(
  p_campaign uuid, p_trigger text, p_severity text, p_detail text, p_evidence jsonb default '{}'::jsonb,
  p_channel text default null, p_signal_at timestamptz default null, p_actor uuid default null
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  c public.campaigns;
  hold_id uuid;
begin
  select * into c from public.campaigns where id = p_campaign for update;
  if c.id is null then raise exception 'campaign not found'; end if;
  select id into hold_id from public.campaign_holds
   where campaign_id = p_campaign and trigger = p_trigger and coalesce(channel, '*') = coalesce(p_channel, '*') and status = 'active';
  if hold_id is not null then
    return hold_id;  -- already held for this reason
  end if;
  insert into public.campaign_holds (campaign_id, org_id, channel, trigger, severity, detail, evidence, signal_at, created_by)
  values (p_campaign, c.org_id, p_channel, p_trigger, p_severity, left(p_detail, 1000), coalesce(p_evidence, '{}'::jsonb),
          coalesce(p_signal_at, now()), p_actor)
  returning id into hold_id;
  if p_severity = 'critical' and c.paused_at is null then
    update public.campaigns set paused_at = now() where id = p_campaign;
  end if;
  perform public.audit(c.org_id, case when p_severity = 'critical' then 'circuit.paused' else 'circuit.warning' end,
    'campaign', p_campaign::text,
    jsonb_build_object('trigger', p_trigger, 'channel', p_channel, 'detail', left(p_detail, 300), 'hold', hold_id));
  return hold_id;
end;
$$;
revoke execute on function public.place_hold(uuid, text, text, text, jsonb, text, timestamptz, uuid) from public, anon, authenticated;
grant execute on function public.place_hold(uuid, text, text, text, jsonb, text, timestamptz, uuid) to service_role;

-- A person pulls the plug (anyone who can approve the campaign): every channel stops now.
create or replace function public.emergency_stop(p_campaign uuid, p_reason text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.campaign_can(p_campaign, 'approve') then
    raise exception 'only owners, admins and approvers can stop a campaign';
  end if;
  if char_length(trim(coalesce(p_reason, ''))) < 10 then
    raise exception 'say why you are stopping it (at least 10 characters)';
  end if;
  return public.place_hold(p_campaign, 'MANUAL_STOP', 'critical', trim(p_reason), '{}'::jsonb, null, now(), auth.uid());
end;
$$;
revoke execute on function public.emergency_stop(uuid, text) from public, anon;
grant execute on function public.emergency_stop(uuid, text) to authenticated;

-- An approver withdraws their Gate 2 approval of the round that's live.
create or replace function public.revoke_approval(p_campaign uuid, p_reason text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.campaign_can(p_campaign, 'approve') then
    raise exception 'only owners, admins and approvers can revoke an approval';
  end if;
  if char_length(trim(coalesce(p_reason, ''))) < 10 then
    raise exception 'say why you are revoking it (at least 10 characters)';
  end if;
  return public.place_hold(p_campaign, 'REVOKED_APPROVAL', 'critical', trim(p_reason),
                           jsonb_build_object('revoked_by', auth.uid()), null, now(), auth.uid());
end;
$$;
revoke execute on function public.revoke_approval(uuid, text) from public, anon;
grant execute on function public.revoke_approval(uuid, text) to authenticated;

-- Resuming is an owner/admin decision with a written note. Resolving the last
-- critical hold un-pauses the campaign and puts its held sends back in the
-- retry queue (they're re-checked before going out). If the condition is still
-- there, the next check simply holds it again.
create or replace function public.resolve_hold(p_hold uuid, p_note text, p_false_alarm boolean default false)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  h public.campaign_holds;
  c public.campaigns;
begin
  select * into h from public.campaign_holds where id = p_hold;
  if h.id is null then raise exception 'hold not found'; end if;
  if not public.campaign_can(h.campaign_id, 'manage') then
    raise exception 'only owners and admins can resume a paused campaign';
  end if;
  if char_length(trim(coalesce(p_note, ''))) < 10 then
    raise exception 'say what was checked or fixed (at least 10 characters)';
  end if;
  select * into c from public.campaigns where id = h.campaign_id for update;
  update public.campaign_holds
     set status = case when p_false_alarm then 'false_alarm' else 'resolved' end,
         resolved_at = now(), resolved_by = auth.uid(), resolution_note = trim(p_note)
   where id = p_hold and status = 'active';
  if not found then raise exception 'this hold is already resolved'; end if;
  if not exists (select 1 from public.campaign_holds
                  where campaign_id = h.campaign_id and status = 'active' and severity = 'critical') then
    update public.campaigns set paused_at = null where id = h.campaign_id;
    update public.deliveries set status = 'failed', next_attempt_at = now(), updated_at = now(),
           last_error = 'held by the circuit breaker, released'
     where campaign_id = h.campaign_id::text and status = 'held';
  end if;
  perform public.audit(c.org_id, 'circuit.resumed', 'campaign', h.campaign_id::text,
    jsonb_build_object('trigger', h.trigger, 'hold', h.id, 'false_alarm', p_false_alarm, 'note', left(trim(p_note), 500)));
end;
$$;
revoke execute on function public.resolve_hold(uuid, text, boolean) from public, anon;
grant execute on function public.resolve_hold(uuid, text, boolean) to authenticated;

-- Owners, admins and marketers set (or clear) when the campaign's offer ends.
create or replace function public.set_offer_end(p_campaign uuid, p_ends_at timestamptz)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  if not (public.campaign_can(p_campaign, 'create') or public.campaign_can(p_campaign, 'manage')) then
    raise exception 'not allowed to change this campaign';
  end if;
  update public.campaigns set offer_ends_at = p_ends_at where id = p_campaign;
  perform public.audit((select org_id from public.campaigns where id = p_campaign), 'campaign.offer_end_set', 'campaign',
    p_campaign::text, jsonb_build_object('offer_ends_at', p_ends_at));
end;
$$;
revoke execute on function public.set_offer_end(uuid, timestamptz) from public, anon;
grant execute on function public.set_offer_end(uuid, timestamptz) to authenticated;

-- The delivery claim, now refusing every send while the campaign (or that
-- channel) is held. It locks the campaign row (shared) before anything else:
-- a pause in progress makes it wait, then see the hold.
create or replace function public.claim_delivery(
  p_campaign_id text,
  p_round integer,
  p_channel text,
  p_user_id uuid,
  p_payload jsonb,
  p_stale_after interval default interval '15 minutes'
)
returns table (verdict text, delivery_id uuid, attempts integer, note text)
language plpgsql
security definer
set search_path = ''
as $$
declare
  d public.deliveries;
  hold public.campaign_holds;
  is_uuid boolean := p_campaign_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
  base_channel text := case when p_channel = 'email_b' then 'email' else p_channel end;
begin
  if is_uuid then
    perform 1 from public.campaigns where id = p_campaign_id::uuid for share;
    select * into hold from public.campaign_holds
     where campaign_id = p_campaign_id::uuid and status = 'active' and severity = 'critical'
       and (channel is null or channel = base_channel)
     order by created_at limit 1;
  end if;

  insert into public.deliveries (campaign_id, round_number, channel, user_id, payload)
  values (p_campaign_id, p_round, p_channel, p_user_id, p_payload)
  on conflict (campaign_id, round_number, channel) do nothing;

  -- Row lock: concurrent claimants queue here, so exactly one of them wins.
  select * into d from public.deliveries
  where campaign_id = p_campaign_id and round_number = p_round and channel = p_channel
  for update;

  if d.status in ('sent', 'dry_run') then
    return query select 'done', d.id, d.attempts, 'skipped: already sent for this campaign/round';
  elsif d.status = 'dead' then
    return query select 'done', d.id, d.attempts,
      format('dead: gave up after %s attempts (%s)', d.attempts, d.last_error);
  elsif hold.id is not null then
    update public.deliveries set status = 'held', payload = p_payload, updated_at = now(),
           last_error = format('held by the circuit breaker: %s', hold.trigger)
     where id = d.id;
    return query select 'held', d.id, d.attempts, format('held: %s (%s)', hold.trigger, left(hold.detail, 200));
  elsif d.status = 'sending' and d.updated_at > now() - p_stale_after then
    return query select 'done', d.id, d.attempts, 'skipped: another worker is sending this right now';
  else
    update public.deliveries
       set status = 'sending', attempts = d.attempts + 1, payload = p_payload, updated_at = now()
     where id = d.id;
    return query select 'go', d.id, d.attempts + 1, null::text;
  end if;
end;
$$;
revoke execute on function public.claim_delivery(text, integer, text, uuid, jsonb, interval) from public, anon, authenticated;
grant execute on function public.claim_delivery(text, integer, text, uuid, jsonb, interval) to service_role;

alter publication supabase_realtime add table public.campaign_holds;
