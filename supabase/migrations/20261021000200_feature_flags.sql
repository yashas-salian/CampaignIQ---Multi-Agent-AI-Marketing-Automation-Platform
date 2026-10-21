-- Feature flags: ship code dark, then turn it on per user, by percentage, or
-- for everyone, without a deploy. One evaluation rule, in SQL, so the Python
-- workers (service role -> feature_enabled_for) and the browser
-- (feature_enabled, for auth.uid()) always agree on who is in a rollout.

create table if not exists public.feature_flags (
  key text primary key check (key ~ '^[a-z][a-z0-9_]{1,63}$'),
  description text not null default '',
  enabled boolean not null default false,          -- kill switch: false = off for everyone
  rollout_percent integer not null default 100 check (rollout_percent between 0 and 100),
  allow_user_ids uuid[] not null default '{}',     -- always on for these users (when enabled)
  updated_at timestamptz not null default now()
);

-- Flags are configuration, not tenant data: readable by signed-in users,
-- writable only with the service role (admin tooling).
alter table public.feature_flags enable row level security;
create policy "feature_flags_read" on public.feature_flags for select to authenticated using (true);

create or replace function public.feature_enabled_for(flag_key text, uid uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select coalesce((
    select f.enabled and (
      uid = any (f.allow_user_ids)
      or f.rollout_percent >= 100
      -- Stable per (flag, user) bucket 0-99, so a user stays in or out of a
      -- rollout as the percentage grows.
      or (uid is not null and abs(hashtext(f.key || ':' || uid::text)) % 100 < f.rollout_percent)
    )
    from public.feature_flags f
    where f.key = flag_key
  ), false);
$$;

-- The browser can only ask about itself (auth.uid() comes from its JWT).
create or replace function public.feature_enabled(flag_key text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select public.feature_enabled_for(flag_key, auth.uid());
$$;

revoke execute on function public.feature_enabled_for(text, uuid) from public, anon, authenticated;
-- Revoking from PUBLIC also removes it from service_role (not a superuser): the
-- Python workers call it with the service-role key.
grant execute on function public.feature_enabled_for(text, uuid) to service_role;
grant execute on function public.feature_enabled(text) to authenticated;
