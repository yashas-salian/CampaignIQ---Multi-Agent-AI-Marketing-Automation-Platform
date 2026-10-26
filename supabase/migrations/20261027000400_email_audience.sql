-- Email engine, part 4: segments, each campaign's fixed audience, batches and unsubscribing.
--
-- A segment is a saved filter over the organisation's contacts. A campaign
-- picks one before Gate 1; when Gate 1 is approved, the people who can be
-- emailed are written to campaign_audience in a stable shuffled order (the
-- proof-of-impact holdout is marked there and never emailed). Each round the
-- worker takes the next batch of people this campaign hasn't emailed yet,
-- re-checking every one of them first. One email per person per campaign.
--
-- Every audience row has its own random unsubscribe token: the link in the
-- email (and the one-click List-Unsubscribe header) unsubscribes that person
-- without a login, and an unknown token reveals nothing.

-- --- Who may be emailed at all ------------------------------------------------------------------
create or replace function public.contact_eligible(c public.contacts)
returns boolean language sql stable security definer set search_path = ''
as $$
  select c.status = 'subscribed'
     and not exists (select 1 from public.email_suppressions s where s.org_id = c.org_id and s.email_hash = public.email_hash(c.email));
$$;

create or replace function public.jsonb_text_array(p jsonb)
returns text[] language sql immutable set search_path = ''
as $$
  select coalesce(array_agg(lower(btrim(x))), '{}') from jsonb_array_elements_text(case when jsonb_typeof(p) = 'array' then p else '[]'::jsonb end) x;
$$;

create or replace function public.contact_purchase_date(c public.contacts)
returns date language sql immutable set search_path = ''
as $$
  select case when c.attributes->>'last_purchase_at' ~ '^\d{4}-\d{2}-\d{2}' then left(c.attributes->>'last_purchase_at', 10)::date end;
$$;

-- Does a contact match a segment filter? Keys (all optional): tags_any, tags_all,
-- tags_none, purchased_within_days, not_purchased_within_days, product_any,
-- country_any, match_campaign_language (default true: same language or unknown).
create or replace function public.contact_in_segment(c public.contacts, f jsonb, p_language text)
returns boolean language sql stable set search_path = ''
as $$
  select (cardinality(public.jsonb_text_array(f->'tags_any')) = 0 or c.tags && public.jsonb_text_array(f->'tags_any'))
     and (c.tags @> public.jsonb_text_array(f->'tags_all'))
     and not (c.tags && public.jsonb_text_array(f->'tags_none'))
     and (f->>'purchased_within_days' is null
          or public.contact_purchase_date(c) >= current_date - (f->>'purchased_within_days')::integer)
     and (f->>'not_purchased_within_days' is null or public.contact_purchase_date(c) is null
          or public.contact_purchase_date(c) < current_date - (f->>'not_purchased_within_days')::integer)
     and (cardinality(public.jsonb_text_array(f->'product_any')) = 0
          or exists (select 1 from jsonb_array_elements_text(coalesce(c.attributes->'products', '[]'::jsonb)) p
                     where lower(btrim(p)) = any(public.jsonb_text_array(f->'product_any'))))
     and (cardinality(public.jsonb_text_array(f->'country_any')) = 0
          or lower(btrim(c.attributes->>'country')) = any(public.jsonb_text_array(f->'country_any')))
     and (coalesce((f->>'match_campaign_language')::boolean, true) = false or c.language is null or p_language is null
          or c.language = p_language);
$$;

-- --- Segments -----------------------------------------------------------------------------------
create table if not exists public.segments (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  filter jsonb not null default '{}'::jsonb check (
    jsonb_typeof(filter) = 'object'
    and (filter - array['tags_any', 'tags_all', 'tags_none', 'purchased_within_days', 'not_purchased_within_days',
                        'product_any', 'country_any', 'match_campaign_language']) = '{}'::jsonb),
  created_by uuid default auth.uid() references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists segments_org_idx on public.segments (org_id);
alter table public.segments enable row level security;
create policy "segments_read" on public.segments for select to authenticated using (public.org_can(org_id, 'view'));
create policy "segments_insert" on public.segments for insert to authenticated with check (public.org_can(org_id, 'create'));
create policy "segments_update" on public.segments for update to authenticated
  using (public.org_can(org_id, 'create')) with check (public.org_can(org_id, 'create'));
create policy "segments_delete" on public.segments for delete to authenticated using (public.org_can(org_id, 'create'));

-- How many people a filter reaches right now (no addresses: any member).
create or replace function public.segment_count(p_org uuid, p_filter jsonb, p_language text)
returns integer
language plpgsql stable security definer set search_path = ''
as $$
begin
  if auth.uid() is not null and not public.org_can(p_org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  return (select count(*) from public.contacts c
          where c.org_id = p_org and public.contact_eligible(c) and public.contact_in_segment(c, coalesce(p_filter, '{}'), p_language));
end;
$$;
revoke execute on function public.segment_count(uuid, jsonb, text) from public, anon;
grant execute on function public.segment_count(uuid, jsonb, text) to authenticated, service_role;

-- --- A campaign's audience ------------------------------------------------------------------------
alter table public.campaigns add column if not exists segment_id uuid references public.segments(id) on delete set null;
alter table public.campaigns add column if not exists email_audience_frozen_at timestamptz;

create table if not exists public.campaign_audience (
  campaign_id uuid not null references public.campaigns(id) on delete cascade,
  contact_id uuid not null references public.contacts(id) on delete cascade,
  position integer not null,
  holdout boolean not null default false,
  excluded_reason text,  -- became un-emailable after the freeze (unsubscribed, bounced, ...)
  unsub_token text not null unique default encode(extensions.gen_random_bytes(16), 'hex'),
  primary key (campaign_id, contact_id)
);
create index if not exists campaign_audience_order_idx on public.campaign_audience (campaign_id, position);
alter table public.campaign_audience enable row level security;
-- No user policy: rows carry unsubscribe tokens. Members see progress through audience_progress().

create or replace function public.set_campaign_segment(p_campaign uuid, p_segment uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  c public.campaigns;
begin
  select * into c from public.campaigns where id = p_campaign for update;
  if c.id is null or not public.org_can(c.org_id, 'create') then
    raise exception 'only owners, admins and marketers can choose the email audience';
  end if;
  if c.email_audience_frozen_at is not null then
    raise exception 'the email audience is fixed once Gate 1 is approved';
  end if;
  if p_segment is not null and not exists (select 1 from public.segments where id = p_segment and org_id = c.org_id) then
    raise exception 'that segment belongs to another organisation';
  end if;
  update public.campaigns set segment_id = p_segment, updated_at = now() where id = p_campaign;
  perform public.audit(c.org_id, 'campaign.email_audience', 'campaign', p_campaign::text, jsonb_build_object('segment', p_segment));
end;
$$;
revoke execute on function public.set_campaign_segment(uuid, uuid) from public, anon;
grant execute on function public.set_campaign_segment(uuid, uuid) to authenticated;

-- Fix the audience when Gate 1 is approved (worker). Runs once; later calls return the same size.
create or replace function public.freeze_campaign_audience(p_campaign uuid)
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  c public.campaigns;
  f jsonb;
begin
  select * into c from public.campaigns where id = p_campaign for update;
  if c.id is null then
    raise exception 'no such campaign';
  end if;
  if c.email_audience_frozen_at is null then
    if c.segment_id is not null then
      select filter into f from public.segments where id = c.segment_id;
      insert into public.campaign_audience (campaign_id, contact_id, position)
      select p_campaign, x.id, row_number() over (order by md5(p_campaign::text || x.id::text))
      from public.contacts x
      where x.org_id = c.org_id and public.contact_eligible(x) and public.contact_in_segment(x, coalesce(f, '{}'), c.target_language);
    end if;
    update public.campaigns set email_audience_frozen_at = now() where id = p_campaign;
  end if;
  return (select count(*) from public.campaign_audience where campaign_id = p_campaign);
end;
$$;

-- The proof-of-impact control group (assigned by the worker over the whole audience).
create or replace function public.set_audience_holdout(p_campaign uuid, p_contacts uuid[])
returns integer
language sql security definer set search_path = ''
as $$
  with u as (update public.campaign_audience set holdout = true where campaign_id = p_campaign and contact_id = any(p_contacts) returning 1)
  select count(*)::integer from u;
$$;

-- The next people to email, in audience order: never anyone this campaign
-- already emailed (or is emailing), never the holdout, and each one re-checked;
-- anyone who can no longer be emailed is marked excluded and skipped.
create or replace function public.email_next_batch(p_campaign uuid, p_size integer)
returns table (contact_id uuid, email text, first_name text, language text, recipient_hash text, unsub_token text,
               consent_source text)
language plpgsql security definer set search_path = ''
as $$
declare
  a record;
  n integer := 0;
begin
  for a in
    select ca.contact_id, ca.unsub_token, x as contact
    from public.campaign_audience ca join public.contacts x on x.id = ca.contact_id
    where ca.campaign_id = p_campaign and not ca.holdout and ca.excluded_reason is null
      and not exists (select 1 from public.email_sends s
                      where s.campaign_id = p_campaign::text and s.contact_id = ca.contact_id and s.status <> 'cancelled')
    order by ca.position
  loop
    exit when n >= greatest(p_size, 0);
    if not public.contact_eligible(a.contact) then
      update public.campaign_audience set excluded_reason = case when (a.contact).status = 'subscribed' then 'suppressed' else (a.contact).status end
      where campaign_id = p_campaign and campaign_audience.contact_id = a.contact_id;
      continue;
    end if;
    contact_id := a.contact_id;
    email := (a.contact).email;
    first_name := (a.contact).first_name;
    language := (a.contact).language;
    recipient_hash := public.email_hash((a.contact).email);
    unsub_token := a.unsub_token;
    consent_source := (a.contact).consent_source;
    n := n + 1;
    return next;
  end loop;
end;
$$;

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
  started integer;
begin
  if auth.uid() is not null and not public.org_can(org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  select count(*), count(*) filter (where ca.holdout), count(*) filter (where ca.excluded_reason is not null)
    into total, holdout, excluded from public.campaign_audience ca where ca.campaign_id = p_campaign;
  select count(distinct s.contact_id) filter (where s.status in ('sent', 'delivered', 'bounced', 'complained')),
         count(distinct s.contact_id) filter (where s.status <> 'cancelled')
    into emailed, started from public.email_sends s where s.campaign_id = p_campaign::text and s.contact_id is not null;
  return jsonb_build_object('total', total, 'emailed', emailed, 'remaining', greatest(total - holdout - excluded - started, 0),
                            'holdout', holdout, 'excluded', excluded);
end;
$$;
revoke execute on function public.audience_progress(uuid) from public, anon;
grant execute on function public.audience_progress(uuid) to authenticated, service_role;

-- --- Unsubscribing (the public unsubscribe Edge Function, service role) ------------------------------
create or replace function public.unsubscribe_info(p_token text)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object('brand', o.name, 'slug', o.slug, 'status', x.status, 'language', coalesce(x.language, c.target_language),
                            'privacy_url', k.privacy_url)
  from public.campaign_audience ca
  join public.contacts x on x.id = ca.contact_id
  join public.campaigns c on c.id = ca.campaign_id
  join public.organizations o on o.id = x.org_id
  left join public.brand_kits k on k.org_id = x.org_id
  where ca.unsub_token = p_token;
$$;

create or replace function public.unsubscribe_by_token(p_token text)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  x public.contacts;
  camp uuid;
begin
  select c.* into x from public.campaign_audience ca join public.contacts c on c.id = ca.contact_id
  where ca.unsub_token = p_token;
  if x.id is null then
    return null;
  end if;
  select ca.campaign_id into camp from public.campaign_audience ca where ca.unsub_token = p_token;
  if x.status in ('subscribed', 'pending') then
    update public.contacts set status = 'unsubscribed', updated_at = now() where id = x.id;
    insert into public.contact_events (org_id, contact_id, kind, actor, details)
    values (x.org_id, x.id, 'unsubscribed', 'contact', jsonb_build_object('campaign', camp));
  end if;
  insert into public.email_suppressions (org_id, email_hash, reason) values (x.org_id, public.email_hash(x.email), 'unsubscribed')
  on conflict do nothing;
  return jsonb_build_object('status', (select status from public.contacts where id = x.id),
                            'brand', (select name from public.organizations where id = x.org_id));
end;
$$;

-- --- The send log knows which contact each row is ---------------------------------------------------
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
                                         last_error, sandbox, sent_at)
    values (p_campaign, p_round, p_channel, r->>'recipient_hash', (r->>'contact_id')::uuid, r->>'status', r->>'resend_id', 1,
            r->>'error', coalesce((r->>'sandbox')::boolean, false), case when r->>'status' = 'sent' then now() end)
    on conflict (campaign_id, round_number, channel, recipient_hash) do update
      set status = excluded.status,
          resend_id = coalesce(excluded.resend_id, s.resend_id),
          contact_id = coalesce(excluded.contact_id, s.contact_id),
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

do $$
declare
  fn text;
begin
  foreach fn in array array['freeze_campaign_audience(uuid)', 'set_audience_holdout(uuid, uuid[])', 'email_next_batch(uuid, integer)',
                            'unsubscribe_info(text)', 'unsubscribe_by_token(text)', 'contact_eligible(public.contacts)']
  loop
    execute format('revoke execute on function public.%s from public, anon, authenticated', fn);
    execute format('grant execute on function public.%s to service_role', fn);
  end loop;
end $$;
