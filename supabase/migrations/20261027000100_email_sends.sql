-- Email engine, part 1: the per-recipient send log.
--
-- `deliveries` keeps one row per (campaign, round, channel): the at-most-once
-- claim, retries and the circuit breaker stay exactly as they are. Under it,
-- email_sends has one row per person emailed that round, so delivery results
-- (from Resend's webhook), batches held for the daily limit or the sending
-- window, and cancellations can be tracked per person. People are identified
-- by a hash of their address, never the address itself.
--
--   queued -> sent -> delivered | bounced | complained
--          -> deferred (daily limit / sending window) -> queued
--          -> failed (retried with the round) | cancelled (campaign stopped)

create table if not exists public.email_sends (
  id bigint generated always as identity primary key,
  campaign_id text not null,             -- text like deliveries: ad-hoc sends have no campaign row
  round_number integer not null,
  channel text not null check (channel in ('email', 'email_b')),
  recipient_hash text not null check (recipient_hash ~ '^[0-9a-f]{2,64}$'),
  status text not null default 'queued'
    check (status in ('queued', 'deferred', 'sent', 'delivered', 'bounced', 'complained', 'failed', 'cancelled')),
  resend_id text,
  attempts integer not null default 0,
  last_error text,
  sandbox boolean not null default false,  -- redirected to the Resend account owner (no verified domain)
  send_after timestamptz,                  -- a deferred send goes out from here
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (campaign_id, round_number, channel, recipient_hash)
);
create index if not exists email_sends_campaign_idx on public.email_sends (campaign_id, round_number);
create index if not exists email_sends_resend_idx on public.email_sends (resend_id) where resend_id is not null;
create index if not exists email_sends_deferred_idx on public.email_sends (send_after) where status = 'deferred';

alter table public.email_sends enable row level security;
create policy "email_sends_read" on public.email_sends for select to authenticated using (
  exists (select 1 from public.campaigns c where c.id::text = email_sends.campaign_id and public.org_can(c.org_id, 'view'))
);

-- The worker logs a round's sends (service role). A retry of the same round
-- updates each person's row; a send that went out never goes back to failed,
-- and only a real new attempt counts.
create or replace function public.record_email_sends(p_campaign text, p_round integer, p_channel text, p_rows jsonb)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  r jsonb;
  n integer := 0;
begin
  for r in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) loop
    insert into public.email_sends as s (campaign_id, round_number, channel, recipient_hash, status, resend_id, attempts,
                                         last_error, sandbox, sent_at)
    values (p_campaign, p_round, p_channel, r->>'recipient_hash', r->>'status', r->>'resend_id', 1, r->>'error',
            coalesce((r->>'sandbox')::boolean, false), case when r->>'status' = 'sent' then now() end)
    on conflict (campaign_id, round_number, channel, recipient_hash) do update
      set status = excluded.status,
          resend_id = coalesce(excluded.resend_id, s.resend_id),
          last_error = excluded.last_error,
          sandbox = excluded.sandbox,
          attempts = s.attempts + 1,
          sent_at = coalesce(s.sent_at, excluded.sent_at),
          updated_at = now()
      where s.status not in ('sent', 'delivered', 'bounced', 'complained');
    n := n + 1;
  end loop;
  return n;
end;
$$;
revoke execute on function public.record_email_sends(text, integer, text, jsonb) from public, anon, authenticated;
grant execute on function public.record_email_sends(text, integer, text, jsonb) to service_role;
