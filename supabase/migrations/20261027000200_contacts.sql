-- Email engine, part 2: each organisation's own contacts, with consent.
--
-- Campaign emails only ever go to a brand's own customers and subscribers who
-- opted in (docs/superpowers/specs/2026-10-26-email-engine-design.md). Every
-- contact carries where and when they agreed (the consent record), every
-- change is in contact_events, and anyone who unsubscribed, bounced,
-- complained or was erased is in email_suppressions (by hash) so no import or
-- API call can bring them back.
--
-- Addresses are personal data: owners, admins and marketers read them;
-- viewers and approvers only see counts (contact_counts). Nobody writes the
-- tables directly; everything goes through the functions below.

alter table public.plan_limits add column if not exists max_contacts integer;
update public.plan_limits set max_contacts = 1000 where plan = 'free' and max_contacts is null;

create table if not exists public.contacts (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  email text not null check (email = lower(btrim(email)) and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' and char_length(email) <= 254),
  first_name text check (char_length(first_name) <= 80),
  name text check (char_length(name) <= 160),
  language text check (language ~ '^[a-z]{2}$'),
  tags text[] not null default '{}' check (cardinality(tags) <= 50),
  attributes jsonb not null default '{}'::jsonb check (jsonb_typeof(attributes) = 'object'),
  status text not null default 'subscribed'
    check (status in ('pending', 'subscribed', 'unsubscribed', 'bounced', 'complained')),
  consent_source text not null
    check (consent_source in ('checkout', 'signup_form', 'in_store', 'event', 'api', 'manual', 'other')),
  consent_note text check (char_length(consent_note) <= 200),
  consent_text text not null check (char_length(consent_text) between 1 and 1000),
  consent_at timestamptz not null default now(),
  confirmed_at timestamptz,
  last_engaged_at timestamptz,
  soft_bounces integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (org_id, email)
);
create index if not exists contacts_org_status_idx on public.contacts (org_id, status);
create index if not exists contacts_tags_idx on public.contacts using gin (tags);

create table if not exists public.contact_events (
  id bigint generated always as identity primary key,
  org_id uuid not null references public.organizations(id) on delete cascade,
  contact_id uuid references public.contacts(id) on delete cascade,
  kind text not null check (kind in ('subscribed', 'confirmed', 'imported', 'updated', 'unsubscribed', 'resubscribed',
                                     'bounced', 'soft_bounced', 'complained', 'clicked', 'purchased', 'erased', 'exported')),
  actor text not null default 'user' check (actor in ('user', 'system', 'contact', 'api')),
  actor_id uuid,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists contact_events_contact_idx on public.contact_events (contact_id, created_at desc);

-- Everyone who must never be emailed again by this organisation, by sha256 of the lowercased address.
create table if not exists public.email_suppressions (
  org_id uuid not null references public.organizations(id) on delete cascade,
  email_hash text not null check (email_hash ~ '^[0-9a-f]{64}$'),
  reason text not null check (reason in ('unsubscribed', 'bounced', 'complained', 'erased')),
  created_at timestamptz not null default now(),
  primary key (org_id, email_hash)
);

alter table public.contacts enable row level security;
alter table public.contact_events enable row level security;
alter table public.email_suppressions enable row level security;
create policy "contacts_read" on public.contacts for select to authenticated using (public.org_can(org_id, 'create'));
create policy "contact_events_read" on public.contact_events for select to authenticated using (public.org_can(org_id, 'create'));
-- email_suppressions: no user policy at all (hashes only, read by the functions).

alter table public.email_sends add column if not exists contact_id uuid references public.contacts(id) on delete set null;
-- One person never gets the same campaign twice (test-inbox sends have no contact).
create unique index if not exists email_sends_one_per_contact on public.email_sends (campaign_id, contact_id)
  where contact_id is not null and status <> 'cancelled';

create or replace function public.email_hash(p_email text)
returns text language sql immutable set search_path = ''
as $$ select encode(extensions.digest(lower(btrim(p_email)), 'sha256'), 'hex') $$;

-- Tags: trimmed, lowercased, at most 40 characters, no repeats, first-seen order kept.
create or replace function public.merge_tags(p_tags text[], p_new jsonb)
returns text[] language sql immutable set search_path = ''
as $$
  select coalesce(array_agg(t order by ord), '{}') from (
    select t, min(ord) as ord from (
      select t, ord from unnest(coalesce(p_tags, '{}')) with ordinality u(t, ord)
      union all
      select left(lower(btrim(x)), 40), 100000 + ord
      from jsonb_array_elements_text(case when jsonb_typeof(p_new) = 'array' then p_new else '[]'::jsonb end) with ordinality j(x, ord)
      where btrim(x) <> ''
    ) a group by t
  ) b;
$$;

create or replace function public.contact_cap(p_org uuid)
returns integer language sql stable security definer set search_path = ''
as $$
  select l.max_contacts from public.organizations o join public.plan_limits l on l.plan = o.plan where o.id = p_org;
$$;

-- Add or update contacts (CSV import from the app; the API calls it as the
-- service role). New people come in subscribed with the consent record the
-- brand attested; known people get their details merged, never their status
-- changed; suppressed addresses are skipped. Returns
-- {added, updated, skipped: [{email, reason}]}.
create or replace function public.upsert_contacts(
  p_org uuid, p_rows jsonb, p_source text, p_note text, p_consent_text text
)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  r jsonb;
  addr text;
  seen text[] := '{}';
  existing public.contacts;
  new_id uuid;
  cap integer := public.contact_cap(p_org);
  have integer;
  added integer := 0;
  updated integer := 0;
  skipped jsonb := '[]'::jsonb;
  is_service boolean := auth.uid() is null;
begin
  if not is_service and not public.org_can(p_org, 'create') then
    raise exception 'only owners, admins and marketers can add contacts';
  end if;
  if p_source is null or p_source not in ('checkout', 'signup_form', 'in_store', 'event', 'api', 'manual', 'other') then
    raise exception 'unknown consent source %', coalesce(p_source, '(none)');
  end if;
  if coalesce(btrim(p_consent_text), '') = '' then
    raise exception 'the consent wording people agreed to is required';
  end if;
  if jsonb_typeof(p_rows) <> 'array' or jsonb_array_length(p_rows) > 1000 then
    raise exception 'send at most 1000 contacts per call';
  end if;
  select count(*) into have from public.contacts where org_id = p_org;

  for r in select * from jsonb_array_elements(p_rows) loop
    addr := lower(btrim(coalesce(r->>'email', '')));
    if addr !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' or char_length(addr) > 254 then
      skipped := skipped || jsonb_build_object('email', left(addr, 254), 'reason', 'invalid');
      continue;
    end if;
    if addr = any(seen) then
      skipped := skipped || jsonb_build_object('email', addr, 'reason', 'duplicate');
      continue;
    end if;
    seen := seen || addr;
    if exists (select 1 from public.email_suppressions where org_id = p_org and email_hash = public.email_hash(addr)) then
      skipped := skipped || jsonb_build_object('email', addr, 'reason', 'suppressed');
      continue;
    end if;

    select * into existing from public.contacts where org_id = p_org and email = addr for update;
    if found then
      update public.contacts set
        first_name = coalesce(nullif(left(btrim(r->>'first_name'), 80), ''), first_name),
        name = coalesce(nullif(left(btrim(r->>'name'), 160), ''), name),
        language = coalesce(case when r->>'language' ~ '^[a-z]{2}$' then r->>'language' end, language),
        tags = public.merge_tags(tags, r->'tags'),
        attributes = attributes || case when jsonb_typeof(r->'attributes') = 'object' then r->'attributes' else '{}'::jsonb end,
        updated_at = now()
      where id = existing.id;
      insert into public.contact_events (org_id, contact_id, kind, actor, actor_id, details)
      values (p_org, existing.id, 'updated', case when is_service then 'api' else 'user' end, auth.uid(), jsonb_build_object('source', p_source));
      updated := updated + 1;
      continue;
    end if;

    if cap is not null and have >= cap then
      skipped := skipped || jsonb_build_object('email', addr, 'reason', 'plan_limit');
      continue;
    end if;
    insert into public.contacts (org_id, email, first_name, name, language, tags, attributes, status,
                                 consent_source, consent_note, consent_text, consent_at)
    values (p_org, addr, nullif(left(btrim(r->>'first_name'), 80), ''), nullif(left(btrim(r->>'name'), 160), ''),
            case when r->>'language' ~ '^[a-z]{2}$' then r->>'language' end,
            public.merge_tags('{}', r->'tags'),
            case when jsonb_typeof(r->'attributes') = 'object' then r->'attributes' else '{}'::jsonb end,
            'subscribed', p_source, nullif(left(btrim(p_note), 200), ''), left(btrim(p_consent_text), 1000),
            coalesce(case when r->>'consent_at' ~ '^\d{4}-\d{2}-\d{2}' then (r->>'consent_at')::timestamptz end, now()))
    returning id into new_id;
    insert into public.contact_events (org_id, contact_id, kind, actor, actor_id, details)
    values (p_org, new_id, 'imported', case when is_service then 'api' else 'user' end, auth.uid(),
            jsonb_build_object('source', p_source, 'note', p_note));
    have := have + 1;
    added := added + 1;
  end loop;

  if added + updated > 0 then
    perform public.audit(p_org, 'contacts.imported', 'organization', p_org::text,
                         jsonb_build_object('added', added, 'updated', updated, 'skipped', jsonb_array_length(skipped), 'source', p_source));
  end if;
  return jsonb_build_object('added', added, 'updated', updated, 'skipped', skipped);
end;
$$;
revoke execute on function public.upsert_contacts(uuid, jsonb, text, text, text) from public, anon;
grant execute on function public.upsert_contacts(uuid, jsonb, text, text, text) to authenticated, service_role;

-- Counts by status, for anyone in the organisation (no addresses).
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
      'cap', public.contact_cap(p_org))
    from public.contacts where org_id = p_org);
end;
$$;
revoke execute on function public.contact_counts(uuid) from public, anon;
grant execute on function public.contact_counts(uuid) to authenticated, service_role;

-- Tags in use with how many subscribed people carry each: for segment filters
-- and the AI audience suggestion. Names and counts only, never addresses.
create or replace function public.contact_tags(p_org uuid)
returns table (tag text, people bigint)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if auth.uid() is not null and not public.org_can(p_org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  return query
    select t, count(*) from public.contacts c, unnest(c.tags) t
    where c.org_id = p_org and c.status = 'subscribed' group by t order by count(*) desc, t limit 200;
end;
$$;
revoke execute on function public.contact_tags(uuid) from public, anon;
grant execute on function public.contact_tags(uuid) to authenticated, service_role;
