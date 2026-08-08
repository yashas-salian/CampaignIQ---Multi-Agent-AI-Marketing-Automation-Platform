-- M3 schema: campaigns/iterations/gates, single-tenant (no RLS/user_id yet — that's M4).
-- Run this once in the Supabase SQL Editor, same project as click_log.sql.

create table if not exists campaigns (
  id uuid primary key default gen_random_uuid(),
  idea text not null,
  domain_category text not null,
  feasibility_score integer,
  feasibility_rationale text,
  status text not null default 'created' check (
    status in (
      'created', 'awaiting_gate_1', 'awaiting_gate_2',
      'awaiting_metrics', 'awaiting_next_round', 'completed', 'rejected'
    )
  ),
  current_round integer not null default 1,
  reddit_subreddit text,
  email_to text[],
  cta_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists personas (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  name text not null,
  demographics text not null,
  psychographics text not null,
  channel_fit text not null,
  messaging_angle text not null,
  is_primary boolean not null default false,
  created_at timestamptz not null default now()
);

create table if not exists iterations (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  round_number integer not null,
  copy_text text,
  image_prompt text,
  preflight_score integer,
  preflight_passed boolean,
  preflight_attempt integer not null default 1,
  bluesky_post_uri text,
  reddit_post_url text,
  email_id text,
  created_at timestamptz not null default now(),
  unique (campaign_id, round_number)
);

create table if not exists gate_decisions (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  gate_number integer not null check (gate_number in (1, 2)),
  round_number integer not null default 1,
  decision text check (decision in ('approve', 'edit', 'reject')),
  comment text,
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  unique (campaign_id, gate_number, round_number)
);
