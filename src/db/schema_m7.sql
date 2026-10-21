-- M7: human category corrections made at Gate 1.
--
-- Run once in the Supabase SQL Editor, after schema_i18n.sql.
--
-- The fine-tuned domain classifier is a distillation of the LLM, so it copies
-- the LLM's mistakes (it never answers "other", over-uses ecommerce_retail).
-- When a user fixes the category at Gate 1, the frontend updates
-- campaigns.domain_category (so the bandit uses the right context for this
-- campaign) and records the correction here. These rows are human-verified
-- labels: the training data a scheduled retrain needs to do better than the
-- teacher. They are users' own content, so any model trained on them must be
-- kept private.

create table if not exists domain_corrections (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references campaigns(id) on delete cascade,
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  idea text not null,
  predicted_domain text not null,
  corrected_domain text not null check (corrected_domain in (
    'fitness_wellness', 'b2b_saas', 'ecommerce_retail', 'food_beverage',
    'finance_fintech', 'education', 'consumer_electronics', 'travel_hospitality',
    'real_estate', 'healthcare', 'entertainment_media', 'other'
  )),
  source text not null default 'gate_1',
  created_at timestamptz not null default now(),
  check (predicted_domain <> corrected_domain)
);

create index if not exists domain_corrections_created_at_idx on domain_corrections (created_at);

-- Users see and add only their own corrections. The retrain job reads all rows
-- with the service-role key (pooling for training is allowed by DESIGN.md; the
-- resulting model is never published).
alter table domain_corrections enable row level security;
create policy "domain_corrections_owner_select" on domain_corrections
  for select using (auth.uid() = user_id);
create policy "domain_corrections_owner_insert" on domain_corrections
  for insert with check (auth.uid() = user_id);
