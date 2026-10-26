-- Email engine, part 8: engagement, and the 24-month sunset.
--
-- Every link in a campaign email carries the person's own click token
-- (campaign_audience.click_token, separate from their unsubscribe token so the
-- brand's site never sees that one): track-click calls touch_contact_click(),
-- which marks them engaged. A purchase the brand reports (POST /v1/conversions
-- with the buyer's email) updates their purchase history and engagement too.
-- Anyone with no click and no purchase for 24 months since they last engaged
-- (or opted in) stops getting campaign email: they stay on the list, shown as
-- inactive, and come back the moment they engage again.

alter table public.campaign_audience add column if not exists click_token text not null unique
  default encode(extensions.gen_random_bytes(16), 'hex');

create table if not exists public.contact_purchases (
  org_id uuid not null references public.organizations(id) on delete cascade,
  event_id text not null,
  created_at timestamptz not null default now(),
  primary key (org_id, event_id)
);
alter table public.contact_purchases enable row level security;  -- workers only

create or replace function public.contact_inactive(c public.contacts)
returns boolean language sql stable set search_path = ''
as $$ select coalesce(c.last_engaged_at, c.consent_at) < now() - interval '24 months' $$;

create or replace function public.contact_eligible(c public.contacts)
returns boolean language sql stable security definer set search_path = ''
as $$
  select c.status = 'subscribed'
     and not public.contact_inactive(c)
     and not exists (select 1 from public.email_suppressions s where s.org_id = c.org_id and s.email_hash = public.email_hash(c.email));
$$;

create or replace function public.contact_counts(p_org uuid)
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
begin
  if auth.uid() is not null and not public.org_can(p_org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  return (
    select jsonb_build_object(
      'total', count(*),
      'subscribed', count(*) filter (where status = 'subscribed'),
      'pending', count(*) filter (where status = 'pending'),
      'unsubscribed', count(*) filter (where status = 'unsubscribed'),
      'bounced', count(*) filter (where status = 'bounced'),
      'complained', count(*) filter (where status = 'complained'),
      'inactive', count(*) filter (where status = 'subscribed' and public.contact_inactive(c)),
      'cap', public.contact_cap(p_org))
    from public.contacts c where org_id = p_org);
end;
$$;

-- A click on a link in a campaign email (track-click, service role).
create or replace function public.touch_contact_click(p_token text)
returns boolean
language plpgsql security definer set search_path = ''
as $$
declare
  a public.campaign_audience;
  x public.contacts;
begin
  select * into a from public.campaign_audience where click_token = p_token;
  if a.contact_id is null then
    return false;
  end if;
  update public.contacts set last_engaged_at = now() where id = a.contact_id returning * into x;
  if not exists (select 1 from public.contact_events where contact_id = x.id and kind = 'clicked' and created_at > now() - interval '1 day') then
    insert into public.contact_events (org_id, contact_id, kind, actor, details)
    values (x.org_id, x.id, 'clicked', 'contact', jsonb_build_object('campaign', a.campaign_id));
  end if;
  return true;
end;
$$;

-- A purchase the brand reported (POST /v1/conversions with the buyer's email):
-- once per event id. Returns 'updated', 'duplicate' or 'unknown' (not a contact).
create or replace function public.record_contact_purchase(
  p_org uuid, p_email text, p_event_id text, p_value numeric, p_currency text, p_products text[], p_at timestamptz
)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  x public.contacts;
  bought timestamptz := least(coalesce(p_at, now()), now());
  products jsonb;
  item text;
begin
  select * into x from public.contacts where org_id = p_org and email = lower(btrim(coalesce(p_email, '')));
  if x.id is null then
    return 'unknown';
  end if;
  insert into public.contact_purchases (org_id, event_id) values (p_org, p_event_id) on conflict do nothing;
  if not found then
    return 'duplicate';
  end if;
  -- Products bought so far, first-seen order, no repeats (case-insensitive), at most 50.
  products := case when jsonb_typeof(x.attributes->'products') = 'array' then x.attributes->'products' else '[]'::jsonb end;
  foreach item in array coalesce(p_products, '{}') loop
    item := left(btrim(item), 80);
    if item <> '' and jsonb_array_length(products) < 50
       and not exists (select 1 from jsonb_array_elements_text(products) e where lower(e) = lower(item)) then
      products := products || to_jsonb(item);
    end if;
  end loop;
  update public.contacts set
    attributes = attributes || jsonb_build_object(
      'last_purchase_at', greatest(coalesce(public.contact_purchase_date(x), date '1900-01-01'), (bought at time zone 'utc')::date)::text,
      'orders', coalesce((attributes->>'orders')::numeric, 0) + 1,
      'products', products
    ) || case when p_value is null then '{}'::jsonb
              else jsonb_build_object('lifetime_value', coalesce((attributes->>'lifetime_value')::numeric, 0) + p_value) end,
    last_engaged_at = greatest(coalesce(last_engaged_at, bought), bought),
    updated_at = now()
  where id = x.id;
  insert into public.contact_events (org_id, contact_id, kind, actor, details)
  values (p_org, x.id, 'purchased', 'api', jsonb_build_object('event_id', p_event_id, 'value', p_value, 'currency', p_currency,
                                                            'products', to_jsonb(coalesce(p_products, '{}'))));
  return 'updated';
end;
$$;

-- The batch also returns each person's click token, and names why someone was skipped.
drop function if exists public.email_next_batch(uuid, integer);
create function public.email_next_batch(p_campaign uuid, p_size integer)
returns table (contact_id uuid, email text, first_name text, language text, recipient_hash text, unsub_token text,
               consent_source text, click_token text)
language plpgsql security definer set search_path = ''
as $$
declare
  a record;
  n integer := 0;
begin
  for a in
    select ca.contact_id, ca.unsub_token, ca.click_token, x as contact
    from public.campaign_audience ca join public.contacts x on x.id = ca.contact_id
    where ca.campaign_id = p_campaign and not ca.holdout and ca.excluded_reason is null
      and not exists (select 1 from public.email_sends s
                      where s.campaign_id = p_campaign::text and s.contact_id = ca.contact_id and s.status <> 'cancelled')
    order by ca.position
  loop
    exit when n >= greatest(p_size, 0);
    if not public.contact_eligible(a.contact) then
      update public.campaign_audience set excluded_reason = case
          when (a.contact).status <> 'subscribed' then (a.contact).status
          when public.contact_inactive(a.contact) then 'inactive'
          else 'suppressed' end
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
    click_token := a.click_token;
    n := n + 1;
    return next;
  end loop;
end;
$$;

do $$
declare
  fn text;
begin
  foreach fn in array array['email_next_batch(uuid, integer)', 'touch_contact_click(text)',
                            'record_contact_purchase(uuid, text, text, numeric, text, text[], timestamptz)']
  loop
    execute format('revoke execute on function public.%s from public, anon, authenticated', fn);
    execute format('grant execute on function public.%s to service_role', fn);
  end loop;
end $$;
