-- Model card for our own domain classifier (the fine-tuned model that sorts
-- campaign ideas into industries). Every promoted version is recorded here by
-- the weekly retrain (src/finetune/retrain.py promote); v1 is seeded from the
-- first evaluation report (src/finetune/reports/20261021-155538.json).
create table if not exists public.model_versions (
  id bigint generated always as identity primary key,
  model text not null default 'domain-classifier',
  version text not null,
  revision text,
  trained_at timestamptz not null,
  base_model text not null,
  method text,
  data jsonb not null default '{}'::jsonb,
  metrics jsonb not null default '{}'::jsonb,
  baseline_metrics jsonb,
  notes text,
  created_at timestamptz not null default now(),
  unique (model, version)
);
-- Written by the service role only; members read it through model_card().
alter table public.model_versions enable row level security;

insert into public.model_versions (model, version, revision, trained_at, base_model, method, data, metrics, baseline_metrics, notes)
values (
  'domain-classifier', 'v1', null, '2026-10-21T10:22:19Z',
  'Qwen2.5-1.5B-Instruct',
  'LoRA fine-tune (rank 16, Unsloth), quantised to 4-bit GGUF; runs on CPU inside the workers',
  '{"synthetic_examples": 560, "train": 417, "validation": 47, "test": 96, "corrections_used": 0, "labels": 12}',
  '{"golden": 0.8333, "golden_n": 18, "heldout": 0.75, "heldout_n": 96, "median_ms": 696, "invalid_outputs": 0,
    "top_confusions": [["food_beverage", "ecommerce_retail", 7], ["b2b_saas", "entertainment_media", 2], ["other", "ecommerce_retail", 3]]}',
  '{"label": "Base Qwen2.5-1.5B (no fine-tuning)", "golden": 0.5556, "heldout": 0.5417, "median_ms": 419, "invalid_outputs": 5}',
  'First release, trained on synthetic ideas only. Gate 1 corrections join from the weekly retrain on.'
)
on conflict (model, version) do nothing;

-- Everything the model card page shows, as one read for any signed-in member.
-- Aggregates only: no idea text, no user data.
create or replace function public.model_card()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
  with dep as (
    select * from public.model_deployments where model = 'domain-classifier'
  ),
  latest as (
    select max(trained_at) as at from public.model_versions where model = 'domain-classifier'
  ),
  shadow as (
    select count(*) as compared, avg(case when s.agreed then 1.0 else 0.0 end) as agreement
    from public.model_shadow_log s, dep
    where s.model = 'domain-classifier' and s.candidate_revision = dep.candidate_revision
      and s.created_at > now() - interval '30 days'
  )
  select jsonb_build_object(
    'versions', coalesce((
      select jsonb_agg(to_jsonb(v) - 'id' - 'created_at' order by v.trained_at desc)
      from public.model_versions v where v.model = 'domain-classifier'
    ), '[]'::jsonb),
    'deployment', (select jsonb_build_object(
      'active_revision', active_revision, 'previous_revision', previous_revision,
      'candidate_revision', candidate_revision, 'mode', mode, 'canary_percent', canary_percent,
      'updated_at', updated_at) from dep),
    'shadow', (select jsonb_build_object('compared', compared, 'agreement', agreement) from shadow),
    'corrections', jsonb_build_object(
      'total', (select count(*) from public.domain_corrections),
      'since_last_training', (select count(*) from public.domain_corrections, latest where created_at > coalesce(latest.at, '-infinity')),
      'last_30_days', (select count(*) from public.domain_corrections where created_at > now() - interval '30 days')
    )
  );
$$;

-- Supabase grants new functions to anon by default; revoking from public doesn't remove that.
revoke all on function public.model_card() from public, anon;
grant execute on function public.model_card() to authenticated, service_role;
