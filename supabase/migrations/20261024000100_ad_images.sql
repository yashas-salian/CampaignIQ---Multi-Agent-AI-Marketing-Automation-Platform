-- Finished ads (src/tools/ad_composer.py): the exact image that gets posted,
-- stored so the campaign page shows it instead of re-drawing from the prompt.
-- Path: {campaign_id}/round-{n}.jpg. Workers
-- upload with the service role; members who can view the campaign can read.
alter table public.iterations add column if not exists image_path text;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('ad-images', 'ad-images', false, 5242880, array['image/jpeg', 'image/png'])
on conflict (id) do nothing;

drop policy if exists "ad images readable by campaign viewers" on storage.objects;
create policy "ad images readable by campaign viewers" on storage.objects
  for select to authenticated
  using (
    bucket_id = 'ad-images'
    and (storage.foldername(name))[1] ~ '^[0-9a-f-]{36}$'
    and public.campaign_can(((storage.foldername(name))[1])::uuid, 'view')
  );
