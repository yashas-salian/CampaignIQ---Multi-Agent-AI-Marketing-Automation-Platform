-- Run this once in the Supabase SQL Editor for your project.
-- Pulled forward from M3's full schema.sql so the M1 `track-click`
-- Edge Function has somewhere to log to; will be folded into the
-- main schema.sql when the rest of the Supabase schema lands in M3.
create table if not exists click_log (
  id uuid primary key default gen_random_uuid(),
  campaign_id text not null,
  round_id integer not null,
  channel text not null,
  destination_url text not null,
  clicked_at timestamptz not null default now()
);
