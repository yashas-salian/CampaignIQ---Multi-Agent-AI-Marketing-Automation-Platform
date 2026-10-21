-- One row per LLM call made through the free-tier gateway
-- (src/providers/gateway.py): which provider served it, tokens, latency,
-- failures. The basis for per-tenant usage limits and cost/latency dashboards.
-- Written by the workers with the service role; users can read their own.

create table if not exists public.llm_usage (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete cascade,  -- null: system calls (eval, MCP without a user)
  provider text not null,
  model text,
  prompt_tokens integer,
  completion_tokens integer,
  latency_ms integer not null,
  ok boolean not null,
  error text,
  created_at timestamptz not null default now()
);

create index if not exists llm_usage_user_created_idx on public.llm_usage (user_id, created_at desc);
create index if not exists llm_usage_created_idx on public.llm_usage (created_at desc);

alter table public.llm_usage enable row level security;
create policy "llm_usage_owner_read" on public.llm_usage for select to authenticated using (auth.uid() = user_id);
