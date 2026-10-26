-- Email engine, part 11: the public API's contact calls (supabase/functions/api).
-- DELETE /v1/contacts/{email} erases a person by address, with the same rules
-- as erasing in the app: only the never-email-again hash stays, audited "api".

create or replace function public.erase_contact_by_email(p_org uuid, p_email text)
returns boolean
language plpgsql security definer set search_path = ''
as $$
declare
  contact uuid := (select id from public.contacts where org_id = p_org and email = lower(btrim(coalesce(p_email, ''))));
begin
  if contact is null then
    -- Not a contact (any more): still make sure they're never added or emailed.
    insert into public.email_suppressions (org_id, email_hash, reason) values (p_org, public.email_hash(p_email), 'erased')
    on conflict (org_id, email_hash) do update set reason = 'erased';
    return false;
  end if;
  perform public.erase_contact_row(contact, 'api');
  return true;
end;
$$;
revoke execute on function public.erase_contact_by_email(uuid, text) from public, anon, authenticated;
grant execute on function public.erase_contact_by_email(uuid, text) to service_role;
