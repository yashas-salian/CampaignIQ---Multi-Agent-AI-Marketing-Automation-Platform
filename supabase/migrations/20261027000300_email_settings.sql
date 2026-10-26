-- Email engine, part 3: each organisation's own Resend account.
--
-- A brand connects its own Resend account (Settings → Email sending). The
-- email-setup Edge Function uses the brand's full-access key once, to list
-- domains, install our webhook and create a sending-only key for the chosen
-- domain; only that sending-only key and the webhook's signing secret are kept,
-- in Supabase Vault. The table keeps pointers and a masked key; the browser
-- never sees a key, and only the service role can read one.
--
-- mode 'live': sends from a verified domain. mode 'sandbox': the account has no
-- verified domain, so Resend only delivers to the account owner's own address;
-- every campaign email is redirected there and labelled (a demo of the whole
-- engine without a domain).

-- --- Brand kit: what every marketing email must show -------------------------------------------
alter table public.brand_kits add column if not exists postal_address text check (char_length(postal_address) <= 300);
alter table public.brand_kits add column if not exists privacy_url text
  check (privacy_url is null or (privacy_url ~ '^https?://[^\s]+$' and char_length(privacy_url) <= 500));

-- --- A short public name for the sign-up link (/join/{slug}) -------------------------------------
alter table public.organizations add column if not exists slug text;

create or replace function public.org_slug(p_name text, p_id uuid)
returns text language plpgsql set search_path = ''
as $$
declare
  base text := nullif(left(btrim(regexp_replace(lower(coalesce(p_name, '')), '[^a-z0-9]+', '-', 'g'), '-'), 40), '');
  candidate text;
begin
  base := coalesce(base, 'brand');
  candidate := base;
  while exists (select 1 from public.organizations where slug = candidate and id <> p_id) loop
    candidate := base || '-' || substr(md5(random()::text), 1, 4);
  end loop;
  return candidate;
end;
$$;

create or replace function public.set_org_slug()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if new.slug is null then
    new.slug := public.org_slug(new.name, new.id);
  end if;
  return new;
end;
$$;
drop trigger if exists organizations_slug on public.organizations;
create trigger organizations_slug before insert on public.organizations for each row execute function public.set_org_slug();

update public.organizations set slug = public.org_slug(name, id) where slug is null;
alter table public.organizations alter column slug set not null;
create unique index if not exists organizations_slug_key on public.organizations (slug);
alter table public.organizations add constraint organizations_slug_format check (slug ~ '^[a-z0-9][a-z0-9-]{0,59}$');

-- --- The connection ----------------------------------------------------------------------------
create table if not exists public.org_email_settings (
  org_id uuid primary key references public.organizations(id) on delete cascade,
  mode text not null check (mode in ('sandbox', 'live')),
  sending_key_secret_id uuid not null,
  masked_key text not null,
  from_email text not null check (from_email ~ '^[^@\s<>]+@[^@\s<>]+$'),
  from_name text not null check (char_length(btrim(from_name)) between 1 and 80),
  reply_to text check (reply_to is null or reply_to ~ '^[^@\s<>]+@[^@\s<>]+$'),
  domain text,
  domain_id text,
  sandbox_to text check (sandbox_to is null or sandbox_to ~ '^[^@\s<>]+@[^@\s<>]+$'),
  webhook_id text,
  webhook_secret_id uuid,
  webhook_ok_at timestamptz,
  daily_limit integer not null default 100 check (daily_limit between 1 and 100000),
  send_window_start smallint not null default 9 check (send_window_start between 0 and 23),
  send_window_end smallint not null default 20 check (send_window_end between 1 and 24),
  timezone text not null default 'UTC',
  paused_reason text,
  connected_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (send_window_start < send_window_end),
  check (mode = 'sandbox' or (domain is not null and from_email like '%@' || domain)),
  check (mode = 'live' or sandbox_to is not null)
);
alter table public.org_email_settings enable row level security;
create policy "org_email_settings_manage_read" on public.org_email_settings for select to authenticated
  using (public.org_can(org_id, 'manage'));

create or replace function public.vault_drop(p_secret uuid)
returns void language plpgsql security definer set search_path = ''
as $$
begin
  if p_secret is not null then
    delete from vault.secrets where id = p_secret;
  end if;
end;
$$;
revoke execute on function public.vault_drop(uuid) from public, anon, authenticated;

-- Called by the email-setup Edge Function (service role) after it has checked
-- the account with the full key and created the sending-only key + webhook.
create or replace function public.save_email_connection(
  p_org uuid, p_mode text, p_sending_key text, p_from_email text, p_from_name text, p_reply_to text,
  p_domain text, p_domain_id text, p_sandbox_to text, p_webhook_id text, p_webhook_secret text
)
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  old public.org_email_settings;
  key_id uuid;
  hook_id uuid;
  masked text := '****' || right(coalesce(p_sending_key, ''), 4);
begin
  if coalesce(length(btrim(p_sending_key)), 0) < 8 then
    raise exception 'sending key looks too short';
  end if;
  select * into old from public.org_email_settings where org_id = p_org for update;
  key_id := vault.create_secret(btrim(p_sending_key), 'email_key:' || p_org || ':' || gen_random_uuid(), 'Resend sending-only key');
  if p_webhook_secret is not null then
    hook_id := vault.create_secret(btrim(p_webhook_secret), 'email_webhook:' || p_org || ':' || gen_random_uuid(), 'Resend webhook signing secret');
  end if;
  insert into public.org_email_settings as s (org_id, mode, sending_key_secret_id, masked_key, from_email, from_name, reply_to,
                                              domain, domain_id, sandbox_to, webhook_id, webhook_secret_id, paused_reason,
                                              connected_at, updated_at)
  values (p_org, p_mode, key_id, masked, lower(btrim(p_from_email)), btrim(p_from_name), nullif(lower(btrim(p_reply_to)), ''),
          nullif(lower(btrim(p_domain)), ''), p_domain_id, nullif(lower(btrim(p_sandbox_to)), ''), p_webhook_id, hook_id, null,
          now(), now())
  on conflict (org_id) do update set
    mode = excluded.mode, sending_key_secret_id = excluded.sending_key_secret_id, masked_key = excluded.masked_key,
    from_email = excluded.from_email, from_name = excluded.from_name, reply_to = excluded.reply_to, domain = excluded.domain,
    domain_id = excluded.domain_id, sandbox_to = excluded.sandbox_to, webhook_id = excluded.webhook_id,
    webhook_secret_id = excluded.webhook_secret_id, webhook_ok_at = null, paused_reason = null,
    connected_at = now(), updated_at = now();
  if old.org_id is not null then
    perform public.vault_drop(old.sending_key_secret_id);
    perform public.vault_drop(old.webhook_secret_id);
  end if;
  perform public.audit(p_org, 'email.connected', 'organization', p_org::text,
                       jsonb_build_object('mode', p_mode, 'domain', p_domain, 'from', p_from_email));
  return masked;
end;
$$;
revoke execute on function public.save_email_connection(uuid, text, text, text, text, text, text, text, text, text, text)
  from public, anon, authenticated;
grant execute on function public.save_email_connection(uuid, text, text, text, text, text, text, text, text, text, text) to service_role;

-- The worker's view of the connection, with the decrypted sending key (service role only).
create or replace function public.email_sending_config(p_org uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object(
    'mode', e.mode, 'api_key', s.decrypted_secret, 'from', e.from_name || ' <' || e.from_email || '>',
    'from_email', e.from_email, 'reply_to', e.reply_to, 'domain', e.domain, 'sandbox_to', e.sandbox_to,
    'daily_limit', e.daily_limit, 'send_window_start', e.send_window_start, 'send_window_end', e.send_window_end,
    'timezone', e.timezone, 'paused_reason', e.paused_reason, 'webhook', e.webhook_id is not null,
    'brand_name', o.name, 'postal_address', k.postal_address, 'privacy_url', k.privacy_url, 'slug', o.slug)
  from public.org_email_settings e
  join vault.decrypted_secrets s on s.id = e.sending_key_secret_id
  join public.organizations o on o.id = e.org_id
  left join public.brand_kits k on k.org_id = e.org_id
  where e.org_id = p_org;
$$;
revoke execute on function public.email_sending_config(uuid) from public, anon, authenticated;
grant execute on function public.email_sending_config(uuid) to service_role;

create or replace function public.email_webhook_secret(p_org uuid)
returns text
language sql stable security definer set search_path = ''
as $$
  select s.decrypted_secret from public.org_email_settings e join vault.decrypted_secrets s on s.id = e.webhook_secret_id
  where e.org_id = p_org;
$$;
revoke execute on function public.email_webhook_secret(uuid) from public, anon, authenticated;
grant execute on function public.email_webhook_secret(uuid) to service_role;

-- What any member may know: connected or not, sandbox or live, which domain, paused and why.
create or replace function public.email_status(p_org uuid)
returns jsonb
language plpgsql stable security definer set search_path = ''
as $$
declare
  e public.org_email_settings;
  k public.brand_kits;
begin
  if auth.uid() is not null and not public.org_can(p_org, 'view') then
    raise exception 'not a member of this organisation';
  end if;
  select * into e from public.org_email_settings where org_id = p_org;
  select * into k from public.brand_kits where org_id = p_org;
  return jsonb_build_object(
    'connected', e.org_id is not null, 'mode', e.mode, 'domain', e.domain, 'from_email', e.from_email, 'from_name', e.from_name,
    'sandbox_to', e.sandbox_to, 'webhook', e.webhook_id is not null, 'webhook_ok_at', e.webhook_ok_at,
    'daily_limit', e.daily_limit, 'send_window_start', e.send_window_start, 'send_window_end', e.send_window_end,
    'timezone', e.timezone, 'paused_reason', e.paused_reason, 'connected_at', e.connected_at,
    'postal_address', k.postal_address is not null and btrim(k.postal_address) <> '',
    'privacy_url', k.privacy_url is not null,
    'slug', (select slug from public.organizations where id = p_org));
end;
$$;
revoke execute on function public.email_status(uuid) from public, anon;
grant execute on function public.email_status(uuid) to authenticated, service_role;

create or replace function public.update_email_preferences(p_org uuid, p_daily_limit integer, p_start integer, p_end integer, p_timezone text)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can change email sending';
  end if;
  if not exists (select 1 from pg_catalog.pg_timezone_names where name = p_timezone) then
    raise exception 'unknown time zone %', p_timezone;
  end if;
  if p_start is null or p_end is null or p_start < 0 or p_end > 24 or p_start >= p_end then
    raise exception 'the sending window must start before it ends, within the day';
  end if;
  update public.org_email_settings
     set daily_limit = p_daily_limit, send_window_start = p_start, send_window_end = p_end, timezone = p_timezone, updated_at = now()
   where org_id = p_org;
  if not found then
    raise exception 'connect a Resend account first';
  end if;
  perform public.audit(p_org, 'email.preferences', 'organization', p_org::text,
                       jsonb_build_object('daily_limit', p_daily_limit, 'window', jsonb_build_array(p_start, p_end), 'timezone', p_timezone));
end;
$$;
revoke execute on function public.update_email_preferences(uuid, integer, integer, integer, text) from public, anon;
grant execute on function public.update_email_preferences(uuid, integer, integer, integer, text) to authenticated;

create or replace function public.disconnect_email(p_org uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  e public.org_email_settings;
begin
  if not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can change email sending';
  end if;
  delete from public.org_email_settings where org_id = p_org returning * into e;
  if e.org_id is not null then
    perform public.vault_drop(e.sending_key_secret_id);
    perform public.vault_drop(e.webhook_secret_id);
    perform public.audit(p_org, 'email.disconnected', 'organization', p_org::text, '{}'::jsonb);
  end if;
end;
$$;
revoke execute on function public.disconnect_email(uuid) from public, anon;
grant execute on function public.disconnect_email(uuid) to authenticated;
