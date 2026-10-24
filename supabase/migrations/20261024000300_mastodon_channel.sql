-- Mastodon as a posting channel: where each round's post went, and the
-- channel name in the delivery ledger and metrics.

alter table public.iterations
  add column if not exists mastodon_post_url text;

alter table public.deliveries drop constraint if exists deliveries_channel_check;
alter table public.deliveries add constraint deliveries_channel_check
  check (channel in ('bluesky', 'mastodon', 'reddit', 'email', 'email_b'));

alter table public.metrics drop constraint if exists metrics_channel_check;
alter table public.metrics add constraint metrics_channel_check
  check (channel in ('bluesky', 'mastodon', 'reddit', 'email', 'email_b'));
