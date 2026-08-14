-- M6 schema: contextual bandit + per-user memory/RAG. Run once in the
-- Supabase SQL Editor, after schema.sql, schema_m4.sql, schema_m5.sql, and
-- schema_templates.sql.

alter table personas add column if not exists age_bracket text;
alter table personas add column if not exists income_tier text;

alter table iterations add column if not exists image_style text;
alter table iterations add column if not exists copy_tone text;
alter table iterations add column if not exists arm_index integer;

-- Shared platform-wide bandit state -- deliberately NOT RLS-isolated (see
-- DESIGN.md: one user's outcome with a creative archetype should improve
-- selection for other users in a similar domain context too). Never stores
-- raw campaign content, only per-arm ridge-regression statistics.
create table if not exists bandit_arms (
  arm_index integer primary key,
  image_style text not null,
  copy_tone text not null,
  a_matrix jsonb not null,
  b_vector jsonb not null,
  pulls integer not null default 0,
  total_reward numeric not null default 0,
  updated_at timestamptz not null default now()
);

-- Per-user memory: retrieval grounding (Feasibility) + novelty-check
-- (Creative) + outcome logging (Feedback & Correction). RLS-scoped per user,
-- unlike bandit_arms above -- this store stays private.
create extension if not exists vector;

create table if not exists embeddings (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  campaign_id uuid references campaigns(id) on delete cascade,
  round_number integer,
  content_type text not null check (content_type in ('idea_persona', 'creative')),
  content_text text not null,
  outcome_reward numeric,
  embedding vector(384),
  created_at timestamptz not null default now()
);
alter table embeddings enable row level security;
create policy "embeddings_owner" on embeddings for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create index if not exists embeddings_vector_idx on embeddings using ivfflat (embedding vector_cosine_ops);

-- Our Python backend always calls this via the service_role key (which
-- bypasses RLS), so match_user_id is an explicit required parameter rather
-- than relying on the function inheriting a caller's RLS context -- same
-- explicit-scoping pattern used everywhere else in this codebase.
create or replace function match_embeddings(
  query_embedding vector(384),
  match_user_id uuid,
  match_content_type text,
  match_count int
)
returns table (
  id uuid,
  campaign_id uuid,
  round_number integer,
  content_text text,
  outcome_reward numeric,
  similarity float
)
language sql stable
as $$
  select
    embeddings.id,
    embeddings.campaign_id,
    embeddings.round_number,
    embeddings.content_text,
    embeddings.outcome_reward,
    1 - (embeddings.embedding <=> query_embedding) as similarity
  from embeddings
  where embeddings.user_id = match_user_id
    and embeddings.content_type = match_content_type
  order by embeddings.embedding <=> query_embedding
  limit match_count;
$$;
