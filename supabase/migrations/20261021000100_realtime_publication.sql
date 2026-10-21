-- Fix: the frontend subscribes to Realtime postgres_changes on these tables
-- (Dashboard, CampaignDetail, Metrics), but they were never added to the
-- supabase_realtime publication, so no change events were ever delivered and
-- pages only refreshed on reload. RLS still applies to Realtime: each user
-- only receives changes to their own rows.
alter publication supabase_realtime add table
  public.campaigns,
  public.iterations,
  public.personas,
  public.gate_decisions,
  public.metrics;
