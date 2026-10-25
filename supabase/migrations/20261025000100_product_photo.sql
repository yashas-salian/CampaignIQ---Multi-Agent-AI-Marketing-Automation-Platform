-- Product-first ads (src/tools/ad_templates.py): every new campaign brings a
-- photo of its product, cut out and set into the ad, and an optional
-- tagline set on it. Older campaigns have neither and keep the old layouts.
alter table public.campaigns add column if not exists product_image_path text;
alter table public.campaigns add column if not exists product_tagline text;
alter table public.campaigns drop constraint if exists campaigns_product_tagline_length;
alter table public.campaigns add constraint campaigns_product_tagline_length
  check (product_tagline is null or char_length(product_tagline) <= 80);

-- Which template a round used and the extra words on it (eyebrow, benefits,
-- steps, badge...), so Gate 2's "New picture" redraws with the same ones.
alter table public.iterations add column if not exists template text;
alter table public.iterations add column if not exists ad_slots jsonb;

-- Product photos, uploaded from the browser before the campaign is created.
-- Path: {user_id}/{uuid}.{ext}. The worker reads them with the service role.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('product-photos', 'product-photos', false, 5242880, array['image/png', 'image/jpeg', 'image/webp'])
on conflict (id) do nothing;

drop policy if exists "product photos uploaded by their owner" on storage.objects;
create policy "product photos uploaded by their owner" on storage.objects
  for insert to authenticated
  with check (bucket_id = 'product-photos' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists "product photos readable by their owner" on storage.objects;
create policy "product photos readable by their owner" on storage.objects
  for select to authenticated
  using (bucket_id = 'product-photos' and (storage.foldername(name))[1] = auth.uid()::text);
