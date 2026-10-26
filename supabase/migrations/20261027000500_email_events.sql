-- Email engine, part 5: what happened to each email (Resend's webhook) and the safety pause.
--
-- The resend-webhook Edge Function verifies each event's signature with the
-- organisation's own signing secret and calls record_email_event():
--   delivered  -> the send is delivered; the person's soft-bounce run resets
--   bounced    -> hard (Permanent): the person is bounced and suppressed at once;
--                 soft (Transient/Undetermined): counted, suppressed at 3 in a row
--   complained -> the person is suppressed for good
-- Events for email CampaignIQ didn't send (the brand's own mail through the same
-- Resend account) or for another organisation are ignored; each event counts once.
--
-- Resend shuts accounts down at a complaint rate of 0.08% or a bounce rate of
-- 4%. Once an organisation has sent at least 200 emails in 30 days, email is
-- paused just before that (0.06% / 3%) and managers are told; a manager
-- resumes it after looking.

create table if not exists public.email_webhook_events (
  event_id text primary key,             -- the Svix message id: retries of one event share it
  org_id uuid not null references public.organizations(id) on delete cascade,
  type text not null,
  received_at timestamptz not null default now()
);
alter table public.email_webhook_events enable row level security;  -- workers only

alter table public.org_email_settings add column if not exists paused_at timestamptz;
alter table public.org_email_settings add column if not exists paused_notified_at timestamptz;

-- Pause the organisation's email if its last 30 days look dangerous. Returns the reason, or null.
create or replace function public.email_safety_check(p_org uuid)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  sent integer;
  bounced integer;
  complained integer;
  reason text;
begin
  select count(*), count(*) filter (where s.status = 'bounced'), count(*) filter (where s.status = 'complained')
    into sent, bounced, complained
  from public.email_sends s join public.campaigns c on c.id::text = s.campaign_id
  where c.org_id = p_org and s.status in ('sent', 'delivered', 'bounced', 'complained') and not s.sandbox
    and coalesce(s.sent_at, s.created_at) > now() - interval '30 days';
  if sent < 200 then
    return null;
  end if;
  if complained::numeric / sent >= 0.0006 then
    reason := format('complaint rate %s%% over the last 30 days (Resend''s limit is 0.08%%)', round(100.0 * complained / sent, 2));
  elsif bounced::numeric / sent >= 0.03 then
    reason := format('bounce rate %s%% over the last 30 days (Resend''s limit is 4%%)', round(100.0 * bounced / sent, 1));
  end if;
  if reason is not null then
    update public.org_email_settings set paused_reason = reason, paused_at = now(), paused_notified_at = null, updated_at = now()
     where org_id = p_org and paused_reason is null;
    if found then
      perform public.audit(p_org, 'email.paused', 'organization', p_org::text, jsonb_build_object('reason', reason));
    end if;
  end if;
  return reason;
end;
$$;

create or replace function public.record_email_event(p_org uuid, p_event_id text, p_type text, p_resend_id text, p_bounce_type text)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  s public.email_sends;
  x public.contacts;
  outcome text;
begin
  insert into public.email_webhook_events (event_id, org_id, type) values (p_event_id, p_org, p_type) on conflict do nothing;
  if not found then
    return 'duplicate';
  end if;
  update public.org_email_settings set webhook_ok_at = now() where org_id = p_org;

  select es.* into s from public.email_sends es join public.campaigns c on c.id::text = es.campaign_id
  where es.resend_id = p_resend_id and c.org_id = p_org
  order by es.id desc limit 1;
  if s.id is null then
    return 'ignored';
  end if;
  select * into x from public.contacts where id = s.contact_id;

  if p_type = 'email.delivered' then
    update public.email_sends set status = 'delivered', updated_at = now() where id = s.id and status = 'sent';
    update public.contacts set soft_bounces = 0 where id = x.id and soft_bounces > 0;
    return 'delivered';
  elsif p_type = 'email.bounced' and coalesce(p_bounce_type, '') = 'Permanent' then
    update public.email_sends set status = 'bounced', last_error = 'hard bounce', updated_at = now() where id = s.id;
    outcome := 'bounced';
  elsif p_type = 'email.bounced' then
    update public.email_sends set last_error = 'soft bounce (' || coalesce(p_bounce_type, 'unknown') || ')', updated_at = now() where id = s.id;
    if x.id is not null then
      update public.contacts set soft_bounces = soft_bounces + 1 where id = x.id returning * into x;
      insert into public.contact_events (org_id, contact_id, kind, actor, details)
      values (p_org, x.id, 'soft_bounced', 'system', jsonb_build_object('campaign', s.campaign_id, 'type', p_bounce_type));
    end if;
    if x.id is null or x.soft_bounces < 3 then
      return 'soft_bounce';
    end if;
    update public.email_sends set status = 'bounced', updated_at = now() where id = s.id;
    outcome := 'bounced';
  elsif p_type = 'email.complained' then
    update public.email_sends set status = 'complained', updated_at = now() where id = s.id;
    outcome := 'complained';
  else
    return 'noted';
  end if;

  if x.id is not null then
    update public.contacts set status = outcome, updated_at = now() where id = x.id and status <> outcome;
    insert into public.contact_events (org_id, contact_id, kind, actor, details)
    values (p_org, x.id, outcome, 'system', jsonb_build_object('campaign', s.campaign_id, 'type', p_bounce_type));
    insert into public.email_suppressions (org_id, email_hash, reason) values (p_org, public.email_hash(x.email), outcome)
    on conflict (org_id, email_hash) do update set reason = case when excluded.reason = 'complained' then 'complained'
                                                                  else public.email_suppressions.reason end;
  end if;
  if public.email_safety_check(p_org) is not null then
    return 'paused';
  end if;
  return outcome;
end;
$$;

create or replace function public.resume_email(p_org uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can change email sending';
  end if;
  update public.org_email_settings set paused_reason = null, paused_at = null, updated_at = now()
   where org_id = p_org and paused_reason is not null;
  perform public.audit(p_org, 'email.resumed', 'organization', p_org::text, '{}'::jsonb);
end;
$$;
revoke execute on function public.resume_email(uuid) from public, anon;
grant execute on function public.resume_email(uuid) to authenticated;

do $$
declare
  fn text;
begin
  foreach fn in array array['email_safety_check(uuid)', 'record_email_event(uuid, text, text, text, text)']
  loop
    execute format('revoke execute on function public.%s from public, anon, authenticated', fn);
    execute format('grant execute on function public.%s to service_role', fn);
  end loop;
end $$;
