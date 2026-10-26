-- Email engine, part 12: what Gate 2 and the campaign page show about email.
--
-- email_round_stats(): per round and email variant, how many went out, were
-- delivered, bounced, were marked as spam, or are still waiting (any member).
-- audience_progress() also says why people left the fixed audience. A "Send
-- me a test" email (the email-test Edge Function) counts against the daily
-- limit like a confirmation does.

alter table public.email_system_sends drop constraint if exists email_system_sends_kind_check;
alter table public.email_system_sends add constraint email_system_sends_kind_check check (kind in ('confirmation', 'test'));

create or replace function public.email_round_stats(p_campaign uuid)
returns table (round_number integer, channel text, sent integer, delivered integer, bounced integer, complained integer,
               waiting integer, sandbox boolean)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if auth.uid() is not null and not public.org_can((select org_id from public.campaigns where id = p_campaign), 'view') then
    raise exception 'not a member of this organisation';
  end if;
  return query
    select s.round_number, s.channel,
           (count(*) filter (where s.status in ('sent', 'delivered', 'bounced', 'complained')))::integer,
           (count(*) filter (where s.status = 'delivered'))::integer,
           (count(*) filter (where s.status = 'bounced'))::integer,
           (count(*) filter (where s.status = 'complained'))::integer,
           (count(*) filter (where s.status in ('queued', 'deferred')))::integer,
           bool_or(s.sandbox)
    from public.email_sends s
    where s.campaign_id = p_campaign::text
    group by s.round_number, s.channel
    order by s.round_number, s.channel;
end;
$$;
revoke execute on function public.email_round_stats(uuid) from public, anon;
grant execute on function public.email_round_stats(uuid) to authenticated, service_role;

create or replace function public.audience_progress(p_campaign uuid)
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
declare
  org uuid := (select org_id from public.campaigns where id = p_campaign);
  total integer;
  holdout integer;
  excluded integer;
  excluded_by jsonb;
  emailed integer;
  waiting integer;
  started integer;
begin
  if auth.uid() is not null and not public.org_can(org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  select count(*), count(*) filter (where ca.holdout), count(*) filter (where ca.excluded_reason is not null)
    into total, holdout, excluded from public.campaign_audience ca where ca.campaign_id = p_campaign;
  select coalesce(jsonb_object_agg(reason, n), '{}'::jsonb) into excluded_by
  from (select ca.excluded_reason as reason, count(*) as n from public.campaign_audience ca
        where ca.campaign_id = p_campaign and ca.excluded_reason is not null group by 1) x;
  select count(distinct s.contact_id) filter (where s.status in ('sent', 'delivered', 'bounced', 'complained')),
         count(distinct s.contact_id) filter (where s.status in ('queued', 'deferred')),
         count(distinct s.contact_id) filter (where s.status <> 'cancelled')
    into emailed, waiting, started from public.email_sends s where s.campaign_id = p_campaign::text and s.contact_id is not null;
  return jsonb_build_object('total', total, 'emailed', emailed, 'waiting', waiting,
                            'remaining', greatest(total - holdout - excluded - started, 0), 'holdout', holdout, 'excluded', excluded,
                            'excluded_by', excluded_by);
end;
$$;
