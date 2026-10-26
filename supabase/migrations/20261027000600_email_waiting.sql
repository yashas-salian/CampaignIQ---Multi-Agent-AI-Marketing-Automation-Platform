-- Email engine, part 6: emails that wait (the daily limit, the sending window) and stopping.
--
-- A round's batch only goes out inside the organisation's sending window and
-- within its daily limit; the rest is logged 'deferred' with the time it may go
-- (send_after). The hourly sweep claims the due ones with email_due_deferred():
-- each person is re-checked first (someone who unsubscribed meanwhile is
-- cancelled, never sent), a campaign held by the circuit breaker keeps its
-- emails waiting, and a stopped or finished campaign cancels them.

-- The log carries the time a deferred send may go.
create or replace function public.record_email_sends(p_campaign text, p_round integer, p_channel text, p_rows jsonb)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  r jsonb;
  n integer := 0;
begin
  for r in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb)) loop
    insert into public.email_sends as s (campaign_id, round_number, channel, recipient_hash, contact_id, status, resend_id, attempts,
                                         last_error, sandbox, send_after, sent_at)
    values (p_campaign, p_round, p_channel, r->>'recipient_hash', (r->>'contact_id')::uuid, r->>'status', r->>'resend_id',
            case when r->>'status' = 'deferred' then 0 else 1 end, r->>'error', coalesce((r->>'sandbox')::boolean, false),
            (r->>'send_after')::timestamptz, case when r->>'status' = 'sent' then now() end)
    on conflict (campaign_id, round_number, channel, recipient_hash) do update
      set status = excluded.status,
          resend_id = coalesce(excluded.resend_id, s.resend_id),
          contact_id = coalesce(excluded.contact_id, s.contact_id),
          last_error = excluded.last_error,
          sandbox = excluded.sandbox,
          send_after = coalesce(excluded.send_after, s.send_after),
          attempts = s.attempts + case when excluded.status = 'deferred' then 0 else 1 end,
          sent_at = coalesce(s.sent_at, excluded.sent_at),
          updated_at = now()
      where s.status not in ('sent', 'delivered', 'bounced', 'complained', 'cancelled');
    n := n + 1;
  end loop;
  return n;
end;
$$;

-- Emails CampaignIQ sent through the organisation's key today (UTC): a sandbox
-- batch is one real email however many people it stood for.
create or replace function public.email_sent_today(p_org uuid)
returns integer
language sql stable security definer set search_path = ''
as $$
  select (count(*) filter (where not s.sandbox) + count(distinct s.resend_id) filter (where s.sandbox))::integer
  from public.email_sends s join public.campaigns c on c.id::text = s.campaign_id
  where c.org_id = p_org and s.status in ('sent', 'delivered', 'bounced', 'complained')
    and s.sent_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc';
$$;

-- The hourly sweep's claim on waiting emails that are due.
create or replace function public.email_due_deferred(p_limit integer)
returns table (campaign_id text, round_number integer, channel text, recipient_hash text, contact_id uuid, org_id uuid)
language plpgsql security definer set search_path = ''
as $$
declare
  r record;
begin
  for r in
    select s.id, s.campaign_id, s.round_number, s.channel, s.recipient_hash, s.contact_id, c.org_id, c.stop_requested, c.status as cstatus,
           x as contact
    from public.email_sends s
    join public.campaigns c on c.id::text = s.campaign_id
    left join public.contacts x on x.id = s.contact_id
    where ((s.status = 'deferred' and s.send_after <= now()) or (s.status = 'queued' and s.updated_at < now() - interval '30 minutes'))
      and c.paused_at is null
    order by s.send_after nulls first
    limit greatest(p_limit, 0)
    for update of s skip locked
  loop
    if r.stop_requested or r.cstatus in ('completed', 'rejected', 'blocked') then
      update public.email_sends set status = 'cancelled', last_error = 'campaign stopped', updated_at = now() where id = r.id;
    elsif (r.contact).id is null or not public.contact_eligible(r.contact) then
      update public.email_sends set status = 'cancelled', last_error = 'no longer subscribed', updated_at = now() where id = r.id;
      update public.campaign_audience set excluded_reason = coalesce((r.contact).status, 'deleted')
       where campaign_audience.campaign_id::text = r.campaign_id and campaign_audience.contact_id = r.contact_id;
    else
      update public.email_sends set status = 'queued', updated_at = now() where id = r.id;
      campaign_id := r.campaign_id;
      round_number := r.round_number;
      channel := r.channel;
      recipient_hash := r.recipient_hash;
      contact_id := r.contact_id;
      org_id := r.org_id;
      return next;
    end if;
  end loop;
end;
$$;

-- Stopping or finishing a campaign cancels what was still waiting.
create or replace function public.cancel_waiting_email()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  if (new.stop_requested and not coalesce(old.stop_requested, false))
     or (new.status in ('completed', 'rejected', 'blocked') and old.status is distinct from new.status) then
    update public.email_sends set status = 'cancelled', last_error = 'campaign stopped', updated_at = now()
     where campaign_id = new.id::text and status in ('queued', 'deferred');
  end if;
  return null;
end;
$$;
drop trigger if exists campaigns_cancel_waiting_email on public.campaigns;
create trigger campaigns_cancel_waiting_email after update of stop_requested, status on public.campaigns
  for each row execute function public.cancel_waiting_email();

-- Progress shows the people waiting for the window or the next day.
create or replace function public.audience_progress(p_campaign uuid)
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
declare
  org uuid := (select org_id from public.campaigns where id = p_campaign);
  total integer;
  holdout integer;
  excluded integer;
  emailed integer;
  waiting integer;
  started integer;
begin
  if auth.uid() is not null and not public.org_can(org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  select count(*), count(*) filter (where ca.holdout), count(*) filter (where ca.excluded_reason is not null)
    into total, holdout, excluded from public.campaign_audience ca where ca.campaign_id = p_campaign;
  select count(distinct s.contact_id) filter (where s.status in ('sent', 'delivered', 'bounced', 'complained')),
         count(distinct s.contact_id) filter (where s.status in ('queued', 'deferred')),
         count(distinct s.contact_id) filter (where s.status <> 'cancelled')
    into emailed, waiting, started from public.email_sends s where s.campaign_id = p_campaign::text and s.contact_id is not null;
  return jsonb_build_object('total', total, 'emailed', emailed, 'waiting', waiting,
                            'remaining', greatest(total - holdout - excluded - started, 0), 'holdout', holdout, 'excluded', excluded);
end;
$$;

do $$
declare
  fn text;
begin
  foreach fn in array array['email_sent_today(uuid)', 'email_due_deferred(integer)']
  loop
    execute format('revoke execute on function public.%s from public, anon, authenticated', fn);
    execute format('grant execute on function public.%s to service_role', fn);
  end loop;
end $$;
