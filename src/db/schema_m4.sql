-- M4 schema: multi-tenancy. Run once in the Supabase SQL Editor, after
-- src/db/schema.sql. Assumes existing M3 test rows have already been
-- cleared (they predate user_id and would violate the NOT NULL below).

-- 1. Add user_id to every M3 tenant-owned table.
alter table campaigns add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table personas add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table iterations add column if not exists user_id uuid references auth.users(id) on delete cascade;
alter table gate_decisions add column if not exists user_id uuid references auth.users(id) on delete cascade;

alter table campaigns alter column user_id set not null;
alter table personas alter column user_id set not null;
alter table iterations alter column user_id set not null;
alter table gate_decisions alter column user_id set not null;

-- 2. Enable RLS + owner-only policies on every tenant-owned table.
alter table campaigns enable row level security;
alter table personas enable row level security;
alter table iterations enable row level security;
alter table gate_decisions enable row level security;

create policy "campaigns_owner" on campaigns for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "personas_owner" on personas for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "iterations_owner" on iterations for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "gate_decisions_owner" on gate_decisions for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- 3. provider_keys: per-user BYOK, encrypted server-side by the
-- submit-provider-key Edge Function. Raw encrypted_key is never exposed to
-- the client — see the provider_keys_masked view below.
create table if not exists provider_keys (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  capability text not null,
  encrypted_key text not null,
  masked_key text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, capability)
);
alter table provider_keys enable row level security;
create policy "provider_keys_owner" on provider_keys for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create view provider_keys_masked as
  select user_id, capability, masked_key, updated_at from provider_keys;
alter view provider_keys_masked set (security_invoker = true);

-- 4. subscriptions: minimal stub flag, not real billing. Regular users can
-- read their own row (for a Settings page tier readout) but never write it
-- — only the service-role admin script (`src/admin/set_subscription.py`)
-- changes tier, so a stub flag can never look like something the user
-- controls themselves.
create table if not exists subscriptions (
  user_id uuid primary key references auth.users(id) on delete cascade,
  status text not null default 'free' check (status in ('free', 'subscribed')),
  updated_at timestamptz not null default now()
);
alter table subscriptions enable row level security;
create policy "subscriptions_owner_read" on subscriptions for select using (auth.uid() = user_id);

-- Auto-create a 'free' subscriptions row for every new signup.
create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.subscriptions (user_id, status) values (new.id, 'free');
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- 5. capability_runs: async standalone-run requests/results for the Tools
-- page (dispatch-and-wait via GitHub Actions, result written back here).
create table if not exists capability_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  capability text not null,
  params jsonb not null default '{}'::jsonb,
  status text not null default 'pending' check (status in ('pending', 'running', 'completed', 'failed')),
  result jsonb,
  error text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);
alter table capability_runs enable row level security;
create policy "capability_runs_owner" on capability_runs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
