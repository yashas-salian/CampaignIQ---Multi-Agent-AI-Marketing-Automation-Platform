-- AI usage & reliability per organisation, per day and provider (managers):
-- calls, failures, tokens, latency p50/p95. Backs the Settings panel; for
-- traces of individual runs, see Langfuse (src/observability.py).
create or replace function public.llm_usage_stats(p_org uuid, p_days integer default 14)
returns table (day date, provider text, calls integer, failures integer, tokens bigint, p50_ms integer, p95_ms integer)
language sql stable security definer set search_path = ''
as $$
  select
    (u.created_at at time zone 'UTC')::date as day,
    u.provider,
    count(*)::int,
    count(*) filter (where not u.ok)::int,
    coalesce(sum(coalesce(u.prompt_tokens, 0) + coalesce(u.completion_tokens, 0)), 0)::bigint,
    (percentile_cont(0.5) within group (order by u.latency_ms))::int,
    (percentile_cont(0.95) within group (order by u.latency_ms))::int
  from public.llm_usage u
  where u.org_id = p_org
    and u.created_at > now() - make_interval(days => least(greatest(p_days, 1), 90))
    and (auth.uid() is null or public.org_can(p_org, 'manage'))
  group by 1, 2
  order by 1 desc, 2;
$$;
revoke execute on function public.llm_usage_stats(uuid, integer) from public, anon;
grant execute on function public.llm_usage_stats(uuid, integer) to authenticated, service_role;
