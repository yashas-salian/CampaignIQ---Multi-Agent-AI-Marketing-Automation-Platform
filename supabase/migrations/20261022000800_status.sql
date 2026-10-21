-- Public status page data. The uptime workflow (every 15 minutes) records one
-- row per component check; /status reads status_summary(), which anyone may
-- call (it exposes only up/down, latency and uptime percentages).

create table if not exists public.status_checks (
  id bigint generated always as identity primary key,
  component text not null,           -- website, database_api, edge_functions, ...
  ok boolean not null,
  latency_ms integer,
  detail text,                        -- short reason when down (no secrets)
  checked_at timestamptz not null default now()
);
create index if not exists status_checks_component_idx on public.status_checks (component, checked_at desc);
alter table public.status_checks enable row level security;
-- No policies: written by the service role, read through status_summary().

create or replace function public.status_summary()
returns jsonb
language sql stable security definer set search_path = ''
as $$
  with latest as (
    select distinct on (component) component, ok, latency_ms, detail, checked_at
    from public.status_checks order by component, checked_at desc
  )
  select jsonb_build_object(
    'checked_at', (select max(checked_at) from public.status_checks),
    'components', coalesce((select jsonb_agg(jsonb_build_object(
        'component', l.component, 'ok', l.ok, 'latency_ms', l.latency_ms,
        'detail', case when l.ok then null else l.detail end, 'checked_at', l.checked_at,
        'uptime_24h', (select round(100.0 * avg(case when c.ok then 1 else 0 end), 2) from public.status_checks c
                       where c.component = l.component and c.checked_at > now() - interval '24 hours'),
        'uptime_7d', (select round(100.0 * avg(case when c.ok then 1 else 0 end), 2) from public.status_checks c
                      where c.component = l.component and c.checked_at > now() - interval '7 days'),
        'history', (select coalesce(jsonb_agg(jsonb_build_object('hour', h.hour, 'ok', h.ok) order by h.hour), '[]'::jsonb)
                    from (select date_trunc('hour', c.checked_at) as hour, bool_and(c.ok) as ok
                          from public.status_checks c
                          where c.component = l.component and c.checked_at > now() - interval '48 hours'
                          group by 1) h)
      ) order by l.component) from latest l), '[]'::jsonb)
  );
$$;
grant execute on function public.status_summary() to anon, authenticated;

-- Keep 30 days of checks.
create or replace function public.prune_status_checks()
returns integer
language sql security definer set search_path = ''
as $$
  with gone as (delete from public.status_checks where checked_at < now() - interval '30 days' returning 1)
  select count(*)::int from gone;
$$;
revoke execute on function public.prune_status_checks() from public, anon, authenticated;
grant execute on function public.prune_status_checks() to service_role;
