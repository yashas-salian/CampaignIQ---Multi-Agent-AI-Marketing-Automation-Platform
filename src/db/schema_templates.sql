-- Templates feature: per-user ad-image / email templates, used opt-in per
-- campaign. Already applied to the live Supabase project (verified live via
-- information_schema.columns after an unrelated git incident) -- this file
-- exists to document it, not to be re-run.

alter table campaigns add column if not exists use_image_template boolean not null default false;
alter table campaigns add column if not exists use_email_template boolean not null default false;

-- Templates persist independent of campaign outcome (not deleted on
-- success/failure) and are stored per (user_id, template_type), so setting
-- a new one just overwrites the last.
create table if not exists templates (
  user_id uuid not null references auth.users(id) on delete cascade,
  template_type text not null check (template_type in ('image', 'email')),
  image_base64 text,
  email_html text,
  updated_at timestamptz not null default now(),
  primary key (user_id, template_type)
);
alter table templates enable row level security;
create policy "templates_owner" on templates for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
