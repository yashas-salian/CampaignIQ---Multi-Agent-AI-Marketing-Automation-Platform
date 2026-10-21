-- Email A/B tests: a campaign can test two creative variants per round. The
-- recipient list is split in halves; variant B goes out on channel 'email_b'
-- (its own delivery row, click tracking and metric row).

alter table public.campaigns add column if not exists ab_test boolean not null default false;

alter table public.iterations
  add column if not exists copy_text_b text,
  add column if not exists image_prompt_b text,
  add column if not exists image_style_b text,
  add column if not exists copy_tone_b text,
  add column if not exists arm_index_b integer,
  add column if not exists email_id_b text;

alter table public.deliveries drop constraint if exists deliveries_channel_check;
alter table public.deliveries add constraint deliveries_channel_check
  check (channel in ('bluesky', 'reddit', 'email', 'email_b'));

alter table public.metrics drop constraint if exists metrics_channel_check;
alter table public.metrics add constraint metrics_channel_check
  check (channel in ('bluesky', 'reddit', 'email', 'email_b'));
