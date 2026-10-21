-- BYOK keys move into Supabase Vault.
--
-- Before: the submit-provider-key Edge Function AES-encrypted the key with
-- SETTINGS_ENCRYPTION_KEY, a secret copied into both the function and the
-- Python workers, and stored the ciphertext in provider_keys.
-- Now: the key lives in vault.secrets (encrypted with a root key that Supabase
-- manages outside the database); provider_keys only keeps a pointer and the
-- masked key for display. Store/read go through SECURITY DEFINER functions
-- that only the service role can call: the browser never sees a key, and
-- neither does any SQL a user can run.
-- Legacy AES rows keep working until src/admin/migrate_keys_to_vault.py
-- moves them.

alter table public.provider_keys add column if not exists vault_secret_id uuid;
alter table public.provider_keys alter column encrypted_key drop not null;

-- Users could UPDATE their own row under the old "for all" policy. With Vault
-- pointers that would let a user point their row at someone else's secret and
-- spend their API key. Users may now only read (via the masked view) and
-- delete their own keys; writes go through store_provider_key().
drop policy if exists "provider_keys_owner" on public.provider_keys;
create policy "provider_keys_owner_read" on public.provider_keys for select to authenticated using (auth.uid() = user_id);
create policy "provider_keys_owner_delete" on public.provider_keys for delete to authenticated using (auth.uid() = user_id);

create or replace function public.store_provider_key(p_user_id uuid, p_capability text, p_api_key text)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  existing uuid;
  secret_id uuid;
  masked text := case when length(p_api_key) >= 4 then '****' || right(p_api_key, 4) else '****' end;
begin
  if p_capability not in ('llm', 'image', 'judge') then
    raise exception 'capability must be one of: llm, image, judge';
  end if;
  if coalesce(length(trim(p_api_key)), 0) < 8 then
    raise exception 'api key looks too short';
  end if;

  select vault_secret_id into existing from public.provider_keys
  where user_id = p_user_id and capability = p_capability
  for update;

  if existing is not null then
    perform vault.update_secret(existing, p_api_key);
    secret_id := existing;
  else
    secret_id := vault.create_secret(
      p_api_key,
      'provider_key:' || p_user_id || ':' || p_capability || ':' || gen_random_uuid(),
      'BYOK provider key'
    );
  end if;

  insert into public.provider_keys (user_id, capability, vault_secret_id, encrypted_key, masked_key, updated_at)
  values (p_user_id, p_capability, secret_id, null, masked, now())
  on conflict (user_id, capability) do update
    set vault_secret_id = excluded.vault_secret_id, encrypted_key = null,
        masked_key = excluded.masked_key, updated_at = now();
  return masked;
end;
$$;

create or replace function public.read_provider_key(p_user_id uuid, p_capability text)
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select s.decrypted_secret
  from public.provider_keys k
  join vault.decrypted_secrets s on s.id = k.vault_secret_id
  where k.user_id = p_user_id and k.capability = p_capability;
$$;

-- Deleting a key (by the user, or with their account) removes the secret too.
create or replace function public.delete_provider_key_secret()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if old.vault_secret_id is not null then
    delete from vault.secrets where id = old.vault_secret_id;
  end if;
  return old;
end;
$$;

drop trigger if exists provider_keys_delete_secret on public.provider_keys;
create trigger provider_keys_delete_secret
  after delete on public.provider_keys
  for each row execute function public.delete_provider_key_secret();

revoke execute on function public.store_provider_key(uuid, text, text) from public, anon, authenticated;
revoke execute on function public.read_provider_key(uuid, text) from public, anon, authenticated;
revoke execute on function public.delete_provider_key_secret() from public, anon, authenticated;
grant execute on function public.store_provider_key(uuid, text, text) to service_role;
grant execute on function public.read_provider_key(uuid, text) to service_role;
