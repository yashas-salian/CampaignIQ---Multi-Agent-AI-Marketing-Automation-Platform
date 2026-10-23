-- Automatic playbooks (src/capabilities/playbooks.py): one per organisation and
-- industry, rewritten when a campaign in that industry finishes. What worked
-- (measured copy tones / visual styles), what to avoid, audience notes and the
-- next thing to test. Future creatives in that industry are written with it.
create table if not exists public.playbooks (
  id bigint generated always as identity primary key,
  org_id uuid not null references public.organizations (id) on delete cascade,
  domain_category text not null,
  -- {headline, do: [], avoid: [], audience: [], next_test}
  content jsonb not null,
  -- {rounds, campaigns, overall_mean, tones: [{name, mean, n}], styles: [...]}
  stats jsonb not null,
  generated_at timestamptz not null default now(),
  unique (org_id, domain_category)
);

alter table public.playbooks enable row level security;
drop policy if exists playbooks_read on public.playbooks;
create policy playbooks_read on public.playbooks for select to authenticated using (public.org_can(org_id, 'view'));
revoke all on public.playbooks from anon;
revoke insert, update, delete, truncate on public.playbooks from authenticated;
