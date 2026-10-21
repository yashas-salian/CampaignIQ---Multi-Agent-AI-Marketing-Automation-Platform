-- Model registry / deployment control for the fine-tuned domain classifier (M7).
--
-- Every promoted model is a commit in the private Hugging Face repo; this row
-- says which commit serves traffic and how a candidate is being tried:
--   mode 'off'     only active_revision is used
--   mode 'shadow'  the candidate also runs on every idea; its answer is only
--                  logged (model_shadow_log), never used
--   mode 'canary'  canary_percent of ideas (stable per idea) use the candidate
-- Rollback = set active_revision back to previous_revision.
-- Only the service role (workers, CLI, admin console) touches these tables.

create table if not exists public.model_deployments (
  model text primary key,
  active_revision text,                 -- null = the repo's latest commit
  previous_revision text,
  candidate_revision text,
  mode text not null default 'off' check (mode in ('off', 'shadow', 'canary')),
  canary_percent integer not null default 0 check (canary_percent between 0 and 100),
  updated_at timestamptz not null default now(),
  updated_by text
);
insert into public.model_deployments (model) values ('domain-classifier') on conflict do nothing;

create table if not exists public.model_shadow_log (
  id bigint generated always as identity primary key,
  model text not null,
  active_revision text,
  candidate_revision text not null,
  active_label text,
  candidate_label text,
  agreed boolean generated always as (active_label is not distinct from candidate_label) stored,
  idea_hash text not null,              -- sha256 prefix: comparable across runs, no content
  created_at timestamptz not null default now()
);
create index if not exists model_shadow_log_candidate_idx on public.model_shadow_log (candidate_revision, created_at desc);

alter table public.model_deployments enable row level security;
alter table public.model_shadow_log enable row level security;
-- No policies: clients can't read or write either table.

create or replace function public.audit_model_deployments()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.audit(null, 'model.deployment_changed', 'model', new.model,
    public.audit_changes(to_jsonb(old), to_jsonb(new), array['updated_at']));
  return null;
end; $$;
drop trigger if exists audit_model_deployments on public.model_deployments;
create trigger audit_model_deployments after update on public.model_deployments
  for each row execute function public.audit_model_deployments();
