-- The on-image words of each round (src/tools/ad_composer.py), so a new
-- picture can be painted at Gate 2 with the same headline and button
-- (capability "ad_image", src/scheduler/run_capability.py). image_version
-- counts those repaints; Gate 2 reloads the stored ad when it's > 0.
alter table public.iterations add column if not exists headline text;
alter table public.iterations add column if not exists cta text;
alter table public.iterations add column if not exists image_version integer not null default 0;

-- Brand logo, placed on every finished ad. Path: {org_id}/logo-{n}.{ext}.
alter table public.brand_kits add column if not exists logo_path text;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('brand-logos', 'brand-logos', false, 1048576, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do nothing;

-- Members see their organisation's logo; owners and admins (who edit the
-- brand kit) upload, replace and remove it. The first folder must be an org id.
drop policy if exists "brand logos readable by members" on storage.objects;
create policy "brand logos readable by members" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'brand-logos'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.org_can(((storage.foldername(name))[1])::uuid, 'view')
  );

drop policy if exists "brand logos uploaded by managers" on storage.objects;
create policy "brand logos uploaded by managers" on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'brand-logos'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.org_can(((storage.foldername(name))[1])::uuid, 'manage')
  );

drop policy if exists "brand logos replaced by managers" on storage.objects;
create policy "brand logos replaced by managers" on storage.objects
  for update to authenticated
  using (
    bucket_id = 'brand-logos'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.org_can(((storage.foldername(name))[1])::uuid, 'manage')
  )
  with check (
    bucket_id = 'brand-logos'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.org_can(((storage.foldername(name))[1])::uuid, 'manage')
  );

drop policy if exists "brand logos removed by managers" on storage.objects;
create policy "brand logos removed by managers" on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'brand-logos'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.org_can(((storage.foldername(name))[1])::uuid, 'manage')
  );
