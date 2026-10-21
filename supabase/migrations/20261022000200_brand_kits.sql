-- Brand kit per organisation: how every campaign in it should sound.
-- Used by creative generation (voice, preferred/forbidden words), the
-- brand-safety guardrails (forbidden words block a draft) and distribution
-- (required sign-off). Members read it; owners/admins edit it.

create table if not exists public.brand_kits (
  org_id uuid primary key references public.organizations(id) on delete cascade,
  voice text not null default '' check (char_length(voice) <= 1000),
  preferred_words text[] not null default '{}',
  forbidden_words text[] not null default '{}',
  required_phrase text check (char_length(required_phrase) <= 80),   -- e.g. "#MadeWithAcme" or "Acme. Cook happy."
  brand_color text check (brand_color ~ '^#[0-9a-fA-F]{6}$'),
  updated_at timestamptz not null default now(),
  check (cardinality(preferred_words) <= 30 and cardinality(forbidden_words) <= 100)
);
alter table public.brand_kits enable row level security;
create policy "brand_kits_read" on public.brand_kits for select to authenticated using (public.org_can(org_id, 'view'));
create policy "brand_kits_insert" on public.brand_kits for insert to authenticated with check (public.org_can(org_id, 'manage'));
create policy "brand_kits_update" on public.brand_kits for update to authenticated
  using (public.org_can(org_id, 'manage')) with check (public.org_can(org_id, 'manage'));

create or replace function public.audit_brand_kits()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.audit(new.org_id, 'brand_kit.updated', 'organization', new.org_id::text,
    case when tg_op = 'INSERT' then '{}'::jsonb
         else public.audit_changes(to_jsonb(old), to_jsonb(new), array['updated_at']) end);
  return null;
end; $$;
drop trigger if exists audit_brand_kits on public.brand_kits;
create trigger audit_brand_kits after insert or update on public.brand_kits
  for each row execute function public.audit_brand_kits();
