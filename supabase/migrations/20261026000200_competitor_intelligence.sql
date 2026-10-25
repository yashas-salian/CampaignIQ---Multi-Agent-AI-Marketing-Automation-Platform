-- Competitor intelligence (src/capabilities/competitors.py, docs/COMPETITOR_INTELLIGENCE.md).
-- An organisation lists competitors and approves the public sources to watch
-- for each (pages it names, an RSS feed, news coverage, public Bluesky posts).
-- The worker turns what changes into timestamped events with their source,
-- folds duplicate and syndicated reports into one story, recommends a response
-- (RESPOND / MONITOR / DIFFERENTIATE / NO_ACTION, always all four considered)
-- and stores a measurable forecast that is checked against what happened.
-- Observed facts (events) and inferred intent (insight explanations) are kept
-- apart. Members read everything; owners, admins and marketers manage the
-- watch list; only the worker writes what was observed.

create table if not exists public.competitors (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 120),
  website text check (website is null or website ~ '^https?://'),
  keywords text[] not null default '{}',           -- how news names them (default: the name)
  category_keyword text check (category_keyword is null or char_length(category_keyword) <= 80),  -- the market they compete in (forecasts)
  markets text[] not null default '{}',            -- ISO country codes, informational
  created_by uuid references auth.users (id) on delete set null,
  created_at timestamptz not null default now(),
  archived_at timestamptz,
  unique (org_id, name)
);

create table if not exists public.competitor_sources (
  id uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references public.competitors (id) on delete cascade,
  org_id uuid not null references public.organizations (id) on delete cascade,
  kind text not null check (kind in ('webpage', 'rss', 'news', 'bluesky')),
  locator text not null check (char_length(locator) between 1 and 500),  -- URL, feed URL, news query or handle
  approved boolean not null default false,  -- nothing is fetched until a person approves the source
  approved_by uuid references auth.users (id) on delete set null,
  approved_at timestamptz,
  status text not null default 'never' check (status in ('never', 'ok', 'stale', 'unavailable', 'blocked_by_robots')),
  last_fetched_at timestamptz,
  last_ok_at timestamptz,
  last_error text,
  created_at timestamptz not null default now(),
  unique (competitor_id, kind, locator)
);

create table if not exists public.competitor_snapshots (
  id bigint generated always as identity primary key,
  source_id uuid not null references public.competitor_sources (id) on delete cascade,
  fetched_at timestamptz not null default now(),
  content_hash text not null,
  extract jsonb not null default '{}'::jsonb  -- headline, offers, prices, claims: short excerpts, not whole pages
);
create index if not exists competitor_snapshots_latest on public.competitor_snapshots (source_id, fetched_at desc);

create table if not exists public.competitor_events (
  id uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references public.competitors (id) on delete cascade,
  org_id uuid not null references public.organizations (id) on delete cascade,
  source_id uuid references public.competitor_sources (id) on delete set null,
  kind text not null check (kind in ('OFFER_CHANGE', 'MESSAGING_SHIFT', 'PRODUCT_LAUNCH', 'CONTENT_THEME')),
  summary text not null,
  observed jsonb not null default '{}'::jsonb,  -- what was seen: before/after quotes, the headline, the offer
  url text,
  outlet text,
  published_at timestamptz,  -- when the source says it happened
  observed_at timestamptz not null default now(),  -- when we saw it
  story_key text not null,   -- duplicate and syndicated reports share one story
  reports integer not null default 1 check (reports >= 1),  -- how many reports of this story arrived
  outlets text[] not null default '{}',
  original_outlet text,      -- the earliest report
  confidence numeric not null default 0.5 check (confidence between 0 and 1),
  unique (competitor_id, story_key)
);
create index if not exists competitor_events_timeline on public.competitor_events (competitor_id, observed_at desc);

create table if not exists public.competitor_insights (
  id uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references public.competitors (id) on delete cascade,
  org_id uuid not null references public.organizations (id) on delete cascade,
  event_id uuid not null references public.competitor_events (id) on delete cascade,
  recommendation text not null check (recommendation in ('RESPOND', 'MONITOR', 'DIFFERENTIATE', 'NO_ACTION')),
  options jsonb not null,         -- all four, each with why / why not
  explanations jsonb not null default '[]'::jsonb,  -- inferred intent: hypotheses, labelled as such, with alternatives
  confidence numeric not null check (confidence between 0 and 1),
  relevance jsonb not null default '{}'::jsonb,
  policy_version text not null,
  status text not null default 'open' check (status in ('open', 'acted', 'dismissed')),
  decided_by uuid references auth.users (id) on delete set null,
  decided_at timestamptz,
  note text,
  created_at timestamptz not null default now(),
  unique (event_id)
);

create table if not exists public.competitor_predictions (
  id uuid primary key default gen_random_uuid(),
  competitor_id uuid not null references public.competitors (id) on delete cascade,
  org_id uuid not null references public.organizations (id) on delete cascade,
  event_id uuid references public.competitor_events (id) on delete set null,
  target text not null default 'search_interest_change' check (target = 'search_interest_change'),
  keyword text not null,
  horizon_days integer not null check (horizon_days between 7 and 56),
  origin_week date not null,      -- the last full week of data the forecast used
  made_at timestamptz not null default now(),
  resolve_after timestamptz not null,
  predicted_change numeric not null,
  interval_low numeric not null,
  interval_high numeric not null,
  interval_level numeric not null default 0.8,
  model_version text not null,
  status text not null default 'pending' check (status in ('pending', 'resolved', 'unresolvable')),
  observed_change numeric,
  inside_interval boolean,
  materialized boolean,           -- did the rise the forecast called (>= 10%) happen?
  abs_error numeric,
  resolved_at timestamptz,
  unique (event_id)
);
create index if not exists competitor_predictions_due on public.competitor_predictions (resolve_after) where status = 'pending';

alter table public.competitors enable row level security;
alter table public.competitor_sources enable row level security;
alter table public.competitor_snapshots enable row level security;
alter table public.competitor_events enable row level security;
alter table public.competitor_insights enable row level security;
alter table public.competitor_predictions enable row level security;

do $$
declare t text;
begin
  foreach t in array array['competitors', 'competitor_sources', 'competitor_events', 'competitor_insights', 'competitor_predictions'] loop
    execute format('drop policy if exists %1$s_read on public.%1$s', t);
    execute format('create policy %1$s_read on public.%1$s for select to authenticated using (public.org_can(org_id, ''view''))', t);
    execute format('revoke all on public.%s from anon', t);
    execute format('revoke insert, update, delete, truncate on public.%s from authenticated', t);
    execute format('grant select on public.%s to authenticated', t);
  end loop;
end $$;
revoke all on public.competitor_snapshots from anon, authenticated;

create or replace function public._competitor_manager(p_org uuid)
returns void
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not (public.org_can(p_org, 'create') or public.org_can(p_org, 'manage')) then
    raise exception 'only owners, admins and marketers can change the competitor watch list';
  end if;
end;
$$;
revoke execute on function public._competitor_manager(uuid) from public, anon, authenticated;

-- Add or update a competitor. The news query defaults to the name.
create or replace function public.upsert_competitor(
  p_org uuid, p_name text, p_website text default null, p_keywords text[] default null,
  p_category_keyword text default null, p_markets text[] default null
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  cid uuid;
begin
  perform public._competitor_manager(p_org);
  insert into public.competitors (org_id, name, website, keywords, category_keyword, markets, created_by)
  values (p_org, trim(p_name), nullif(trim(p_website), ''), coalesce(p_keywords, array[trim(p_name)]),
          nullif(trim(p_category_keyword), ''), coalesce(p_markets, '{}'), auth.uid())
  on conflict (org_id, name) do update set
    website = excluded.website, keywords = excluded.keywords, category_keyword = excluded.category_keyword,
    markets = excluded.markets, archived_at = null
  returning id into cid;
  perform public.audit(p_org, 'competitor.saved', 'competitor', cid::text, jsonb_build_object('name', trim(p_name)));
  return cid;
end;
$$;
revoke execute on function public.upsert_competitor(uuid, text, text, text[], text, text[]) from public, anon;
grant execute on function public.upsert_competitor(uuid, text, text, text[], text, text[]) to authenticated;

create or replace function public.archive_competitor(p_competitor uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  c public.competitors;
begin
  select * into c from public.competitors where id = p_competitor;
  if c.id is null then raise exception 'competitor not found'; end if;
  perform public._competitor_manager(c.org_id);
  update public.competitors set archived_at = now() where id = p_competitor;
  update public.competitor_sources set approved = false where competitor_id = p_competitor;
  perform public.audit(c.org_id, 'competitor.archived', 'competitor', c.id::text, jsonb_build_object('name', c.name));
end;
$$;
revoke execute on function public.archive_competitor(uuid) from public, anon;
grant execute on function public.archive_competitor(uuid) to authenticated;

-- Propose a source; it stays unapproved (never fetched) until someone approves it.
create or replace function public.add_competitor_source(p_competitor uuid, p_kind text, p_locator text, p_approve boolean default false)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  c public.competitors;
  sid uuid;
  loc text := trim(p_locator);
begin
  select * into c from public.competitors where id = p_competitor;
  if c.id is null then raise exception 'competitor not found'; end if;
  perform public._competitor_manager(c.org_id);
  if p_kind in ('webpage', 'rss') and loc !~ '^https?://[^/\s]+' then
    raise exception 'a page or feed source needs a web address';
  end if;
  if p_kind = 'bluesky' then loc := lower(regexp_replace(loc, '^@', '')); end if;
  insert into public.competitor_sources (competitor_id, org_id, kind, locator, approved, approved_by, approved_at)
  values (p_competitor, c.org_id, p_kind, loc, p_approve, case when p_approve then auth.uid() end, case when p_approve then now() end)
  on conflict (competitor_id, kind, locator) do update set approved = excluded.approved or public.competitor_sources.approved
  returning id into sid;
  perform public.audit(c.org_id, 'competitor.source_added', 'competitor', c.id::text,
    jsonb_build_object('kind', p_kind, 'locator', loc, 'approved', p_approve));
  return sid;
end;
$$;
revoke execute on function public.add_competitor_source(uuid, text, text, boolean) from public, anon;
grant execute on function public.add_competitor_source(uuid, text, text, boolean) to authenticated;

create or replace function public.approve_competitor_source(p_source uuid, p_approved boolean)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  s public.competitor_sources;
begin
  select * into s from public.competitor_sources where id = p_source;
  if s.id is null then raise exception 'source not found'; end if;
  perform public._competitor_manager(s.org_id);
  update public.competitor_sources
     set approved = p_approved, approved_by = case when p_approved then auth.uid() end,
         approved_at = case when p_approved then now() end
   where id = p_source;
  perform public.audit(s.org_id, case when p_approved then 'competitor.source_approved' else 'competitor.source_paused' end,
    'competitor', s.competitor_id::text, jsonb_build_object('kind', s.kind, 'locator', s.locator));
end;
$$;
revoke execute on function public.approve_competitor_source(uuid, boolean) from public, anon;
grant execute on function public.approve_competitor_source(uuid, boolean) to authenticated;

-- A person records what they did about an insight (acted on it / dismissed it), with a note.
create or replace function public.decide_competitor_insight(p_insight uuid, p_status text, p_note text default null)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  i public.competitor_insights;
begin
  select * into i from public.competitor_insights where id = p_insight;
  if i.id is null then raise exception 'insight not found'; end if;
  perform public._competitor_manager(i.org_id);
  if p_status not in ('open', 'acted', 'dismissed') then raise exception 'unknown status'; end if;
  update public.competitor_insights
     set status = p_status, decided_by = auth.uid(), decided_at = now(), note = nullif(trim(p_note), '')
   where id = p_insight;
  perform public.audit(i.org_id, 'competitor.insight_' || p_status, 'competitor', i.competitor_id::text,
    jsonb_build_object('insight', i.id, 'recommendation', i.recommendation, 'note', left(coalesce(p_note, ''), 300)));
end;
$$;
revoke execute on function public.decide_competitor_insight(uuid, text, text) from public, anon;
grant execute on function public.decide_competitor_insight(uuid, text, text) to authenticated;

-- The worker's write for an observed event: a repeat of a known story only
-- adds its outlet (it isn't a new, independent signal). Returns the event id
-- and whether it's new.
create or replace function public.record_competitor_event(
  p_competitor uuid, p_source uuid, p_kind text, p_summary text, p_observed jsonb, p_url text, p_outlet text,
  p_published_at timestamptz, p_story_key text, p_confidence numeric
)
returns table (event_id uuid, is_new boolean)
language plpgsql security definer set search_path = ''
as $$
declare
  c public.competitors;
  e public.competitor_events;
begin
  select * into c from public.competitors where id = p_competitor;
  select * into e from public.competitor_events where competitor_id = p_competitor and story_key = p_story_key for update;
  if e.id is not null then
    update public.competitor_events
       set reports = reports + 1,
           outlets = case when p_outlet is null or p_outlet = any (outlets) then outlets else outlets || p_outlet end,
           original_outlet = case when p_published_at is not null and (published_at is null or p_published_at < published_at)
                                  then p_outlet else original_outlet end,
           published_at = least(published_at, p_published_at)
     where id = e.id;
    return query select e.id, false;
    return;
  end if;
  insert into public.competitor_events (competitor_id, org_id, source_id, kind, summary, observed, url, outlet, published_at,
                                        story_key, outlets, original_outlet, confidence)
  values (p_competitor, c.org_id, p_source, p_kind, left(p_summary, 500), coalesce(p_observed, '{}'::jsonb), p_url, p_outlet,
          p_published_at, p_story_key, case when p_outlet is null then '{}' else array[p_outlet] end, p_outlet, p_confidence)
  returning id into e.id;
  return query select e.id, true;
end;
$$;
revoke execute on function public.record_competitor_event(uuid, uuid, text, text, jsonb, text, text, timestamptz, text, numeric) from public, anon, authenticated;
grant execute on function public.record_competitor_event(uuid, uuid, text, text, jsonb, text, text, timestamptz, text, numeric) to service_role;

do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'competitor_events') then
      alter publication supabase_realtime add table public.competitor_events;
    end if;
    if not exists (select 1 from pg_publication_tables where pubname = 'supabase_realtime' and tablename = 'competitor_insights') then
      alter publication supabase_realtime add table public.competitor_insights;
    end if;
  end if;
end $$;
