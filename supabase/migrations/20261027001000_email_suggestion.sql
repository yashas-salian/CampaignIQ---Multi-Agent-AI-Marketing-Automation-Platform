-- Email engine, part 10: the AI's suggested email audience at Gate 1.
--
-- After personas are written, the worker shows the model a catalogue of the
-- organisation's contacts made only of names and counts (tags, products,
-- countries, languages, how recently people bought): never an address, a name
-- or a single person's record. The model proposes a segment filter using only
-- what's in the catalogue; the worker drops anything else and stores the
-- suggestion on the campaign. A person accepts it at Gate 1 (it becomes a
-- saved segment and the campaign's audience) or picks another; it's never
-- applied by itself.

alter table public.campaigns add column if not exists email_suggestion jsonb;

create or replace function public.contact_catalog(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  with live as (select * from public.contacts c where c.org_id = p_org and public.contact_eligible(c))
  select jsonb_build_object(
    'subscribed', (select count(*) from live),
    'tags', coalesce((select jsonb_agg(jsonb_build_object('name', t, 'people', n) order by n desc, t)
                      from (select t, count(*) as n from live, unnest(live.tags) t group by t order by n desc, t limit 60) x), '[]'::jsonb),
    'products', coalesce((select jsonb_agg(jsonb_build_object('name', p, 'people', n) order by n desc, p)
                          from (select lower(btrim(p)) as p, count(distinct live.id) as n
                                from live, jsonb_array_elements_text(case when jsonb_typeof(live.attributes->'products') = 'array'
                                                                          then live.attributes->'products' else '[]'::jsonb end) p
                                group by lower(btrim(p)) order by n desc limit 30) x), '[]'::jsonb),
    'countries', coalesce((select jsonb_agg(jsonb_build_object('name', c, 'people', n) order by n desc, c)
                           from (select lower(btrim(live.attributes->>'country')) as c, count(*) as n from live
                                 where coalesce(btrim(live.attributes->>'country'), '') <> '' group by 1 order by n desc limit 20) x), '[]'::jsonb),
    'languages', coalesce((select jsonb_agg(jsonb_build_object('name', l, 'people', n) order by n desc)
                           from (select coalesce(live.language, 'unknown') as l, count(*) as n from live group by 1) x), '[]'::jsonb),
    'purchased_within', jsonb_build_object(
      '30', (select count(*) from live where public.contact_purchase_date(live) >= current_date - 30),
      '90', (select count(*) from live where public.contact_purchase_date(live) >= current_date - 90),
      '365', (select count(*) from live where public.contact_purchase_date(live) >= current_date - 365),
      'never', (select count(*) from live where public.contact_purchase_date(live) is null)));
$$;
revoke execute on function public.contact_catalog(uuid) from public, anon, authenticated;
grant execute on function public.contact_catalog(uuid) to service_role;

-- "Use this audience" at Gate 1: the suggestion becomes a saved segment and the campaign's audience.
create or replace function public.accept_email_suggestion(p_campaign uuid)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  c public.campaigns;
  seg uuid;
begin
  select * into c from public.campaigns where id = p_campaign;
  if c.id is null or not public.org_can(c.org_id, 'create') then
    raise exception 'only owners, admins and marketers can choose the email audience';
  end if;
  if c.email_audience_frozen_at is not null then
    raise exception 'the email audience is fixed once Gate 1 is approved';
  end if;
  if c.email_suggestion is null or jsonb_typeof(c.email_suggestion->'filter') <> 'object' then
    raise exception 'this campaign has no suggested audience';
  end if;
  insert into public.segments (org_id, name, filter, created_by)
  values (c.org_id, left('Suggested: ' || btrim(c.idea), 80), c.email_suggestion->'filter', auth.uid())
  returning id into seg;
  perform public.set_campaign_segment(p_campaign, seg);
  return seg;
end;
$$;
revoke execute on function public.accept_email_suggestion(uuid) from public, anon;
grant execute on function public.accept_email_suggestion(uuid) to authenticated;
