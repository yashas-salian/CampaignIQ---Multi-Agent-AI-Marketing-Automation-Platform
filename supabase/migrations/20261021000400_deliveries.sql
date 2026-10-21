-- Delivery ledger: one row per (campaign, round, channel) send.
--
-- Replaces the local .local_dedup_store.json, which didn't survive between
-- GitHub Actions runs (every run starts on a fresh machine), and makes failed
-- sends retryable instead of crashing the run:
--   pending -> sending -> sent | dry_run
--                      -> failed (retried with backoff by the scheduler)
--                      -> dead   (gave up after max attempts: the dead-letter queue)
-- A worker only sends after atomically moving a row into 'sending', so two
-- workers can never deliver the same round twice.

create table if not exists public.deliveries (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null,          -- text, not an FK: ad-hoc MCP sends have no campaign row
  user_id uuid references auth.users(id) on delete cascade,
  round_number integer not null,
  channel text not null check (channel in ('bluesky', 'reddit', 'email')),
  status text not null default 'pending'
    check (status in ('pending', 'sending', 'sent', 'dry_run', 'failed', 'dead')),
  attempts integer not null default 0,
  payload jsonb not null default '{}'::jsonb,  -- what to (re)send
  result_ref text,                    -- post URI / email id once sent
  last_error text,
  next_attempt_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (campaign_id, round_number, channel)
);

create index if not exists deliveries_retry_idx on public.deliveries (next_attempt_at) where status = 'failed';
create index if not exists deliveries_dead_idx on public.deliveries (updated_at desc) where status = 'dead';

alter table public.deliveries enable row level security;
create policy "deliveries_owner_read" on public.deliveries for select to authenticated using (auth.uid() = user_id);

-- Atomic claim, called by the workers (service role). Returns one row:
--   verdict 'go'   -> caller may send now (row is 'sending', attempts counted)
--   verdict 'done' -> don't send; note says why (already sent, dead, in flight)
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
begin
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
