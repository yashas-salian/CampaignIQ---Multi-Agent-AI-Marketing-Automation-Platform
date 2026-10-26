-- Email engine, part 9: the brand's customers' data rights.
--
-- Owners and admins can export every contact with their consent history (for
-- a data request, or to leave) and erase a person. Erasing deletes the contact
-- and their history, unlinks their past sends, and keeps only the hash in
-- email_suppressions so no import, API call or sign-up can ever bring them
-- back. The person can erase themselves from the unsubscribe page ("Also
-- delete my details"). Both are audited without the address.

create or replace function public.erase_contact_row(p_contact uuid, p_by text)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  x public.contacts;
begin
  select * into x from public.contacts where id = p_contact for update;
  if x.id is null then
    return;
  end if;
  insert into public.email_suppressions (org_id, email_hash, reason) values (x.org_id, public.email_hash(x.email), 'erased')
  on conflict (org_id, email_hash) do update set reason = 'erased';
  update public.email_sends set recipient_hash = encode(extensions.gen_random_bytes(32), 'hex'), contact_id = null
   where contact_id = x.id;
  delete from public.contacts where id = x.id;  -- events, audience rows and tokens go with it
  perform public.audit(x.org_id, 'contact.erased', 'contact', x.id::text, jsonb_build_object('by', p_by));
end;
$$;
revoke execute on function public.erase_contact_row(uuid, text) from public, anon, authenticated;

create or replace function public.erase_contact(p_contact uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  org uuid := (select org_id from public.contacts where id = p_contact);
begin
  if org is null or not public.org_can(org, 'manage') then
    raise exception 'only owners and admins can erase a contact';
  end if;
  perform public.erase_contact_row(p_contact, 'member');
end;
$$;
revoke execute on function public.erase_contact(uuid) from public, anon;
grant execute on function public.erase_contact(uuid) to authenticated;

-- "Also delete my details" on the unsubscribe page (the unsubscribe Edge Function, service role).
create or replace function public.erase_by_token(p_token text)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  contact uuid;
  brand text;
begin
  select ca.contact_id, o.name into contact, brand
  from public.campaign_audience ca join public.contacts c on c.id = ca.contact_id join public.organizations o on o.id = c.org_id
  where ca.unsub_token = p_token;
  if contact is null then
    return null;
  end if;
  perform public.erase_contact_row(contact, 'the person');
  return jsonb_build_object('status', 'erased', 'brand', brand);
end;
$$;
revoke execute on function public.erase_by_token(text) from public, anon, authenticated;
grant execute on function public.erase_by_token(text) to service_role;

create or replace function public.export_contacts(p_org uuid)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  out jsonb;
begin
  if not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can export contacts';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
      'email', c.email, 'first_name', c.first_name, 'name', c.name, 'language', c.language, 'tags', c.tags, 'attributes', c.attributes,
      'status', c.status, 'consent_source', c.consent_source, 'consent_note', c.consent_note, 'consent_text', c.consent_text,
      'consent_at', c.consent_at, 'confirmed_at', c.confirmed_at, 'last_engaged_at', c.last_engaged_at, 'created_at', c.created_at,
      'history', (select coalesce(jsonb_agg(jsonb_build_object('kind', e.kind, 'actor', e.actor, 'at', e.created_at, 'details', e.details)
                                            order by e.created_at), '[]'::jsonb)
                  from public.contact_events e where e.contact_id = c.id))
    order by c.created_at), '[]'::jsonb)
    into out
  from public.contacts c where c.org_id = p_org;
  perform public.audit(p_org, 'contacts.exported', 'organization', p_org::text, jsonb_build_object('contacts', jsonb_array_length(out)));
  return out;
end;
$$;
revoke execute on function public.export_contacts(uuid) from public, anon;
grant execute on function public.export_contacts(uuid) to authenticated;
