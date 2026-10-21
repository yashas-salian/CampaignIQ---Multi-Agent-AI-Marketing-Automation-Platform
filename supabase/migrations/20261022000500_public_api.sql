-- Public API keys and outbound webhooks.
--
-- API keys: "mos_" + 48 hex chars, shown once at creation; only a SHA-256 hash
-- is stored. Scopes: 'read' and/or 'write'. Used by the `api` Edge Function,
-- which resolves a key with api_key_lookup() (service role) and enforces a
-- per-key rate limit there.
-- Webhooks: every audit event in an organisation can be POSTed to its HTTPS
-- endpoints, signed with HMAC-SHA256. The first attempt goes out at once via
-- pg_net; the sweep (src/scheduler/webhooks.py) confirms responses and retries
-- failures with backoff.

create extension if not exists pg_net with schema extensions;

-- --- API keys ----------------------------------------------------------------

create table if not exists public.api_keys (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  name text not null check (char_length(trim(name)) between 1 and 60),
  prefix text not null,                      -- first 12 chars, to recognise a key in lists
  key_hash text not null unique,
  scopes text[] not null default '{read}' check (scopes <@ array['read', 'write'] and cardinality(scopes) > 0),
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz,
  revoked_at timestamptz
);
alter table public.api_keys enable row level security;
create policy "api_keys_manage_read" on public.api_keys for select to authenticated using (public.org_can(org_id, 'manage'));

create table if not exists public.api_rate (
  key_id uuid not null references public.api_keys(id) on delete cascade,
  window_start timestamptz not null,
  hits integer not null default 0,
  primary key (key_id, window_start)
);
alter table public.api_rate enable row level security;

create or replace function public.create_api_key(p_org uuid, p_name text, p_scopes text[] default '{read}')
returns text
language plpgsql security definer set search_path = ''
as $$
declare raw text := 'mos_' || encode(extensions.gen_random_bytes(24), 'hex');
begin
  if not public.org_can(p_org, 'manage') then raise exception 'only owners and admins can create API keys'; end if;
  insert into public.api_keys (org_id, name, prefix, key_hash, scopes, created_by)
  values (p_org, trim(p_name), left(raw, 12), encode(extensions.digest(raw, 'sha256'), 'hex'), p_scopes, auth.uid());
  perform public.audit(p_org, 'api_key.created', 'api_key', left(raw, 12), jsonb_build_object('name', trim(p_name), 'scopes', p_scopes));
  return raw;
end;
$$;

create or replace function public.revoke_api_key(p_key uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare k public.api_keys;
begin
  select * into k from public.api_keys where id = p_key;
  if k.id is null or not public.org_can(k.org_id, 'manage') then raise exception 'not allowed'; end if;
  update public.api_keys set revoked_at = now() where id = p_key and revoked_at is null;
  perform public.audit(k.org_id, 'api_key.revoked', 'api_key', k.prefix, '{}'::jsonb);
end;
$$;

-- Service role only. Returns the key's org/scopes/creator if it's valid and
-- under its rate limit (p_limit requests per minute), else nothing.
create or replace function public.api_key_lookup(p_raw text, p_limit integer default 60)
returns table (key_id uuid, org_id uuid, scopes text[], created_by uuid, rate_limited boolean)
language plpgsql security definer set search_path = ''
as $$
#variable_conflict use_column
declare
  k public.api_keys;
  window_ts timestamptz := date_trunc('minute', now());
  used integer;
begin
  select * into k from public.api_keys
  where key_hash = encode(extensions.digest(coalesce(p_raw, ''), 'sha256'), 'hex') and revoked_at is null;
  if k.id is null then return; end if;
  insert into public.api_rate (key_id, window_start, hits) values (k.id, window_ts, 1)
  on conflict (key_id, window_start) do update set hits = public.api_rate.hits + 1
  returning hits into used;
  delete from public.api_rate where key_id = k.id and window_start < window_ts - interval '10 minutes';
  update public.api_keys set last_used_at = now() where id = k.id;
  return query select k.id, k.org_id, k.scopes, k.created_by, used > p_limit;
end;
$$;

-- --- Webhooks ----------------------------------------------------------------

create table if not exists public.webhooks (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  url text not null check (url ~ '^https://[^\s/$.?#].[^\s]*$'),
  secret text not null default encode(extensions.gen_random_bytes(24), 'hex'),
  events text[] not null default '{*}',      -- audit actions or prefixes ('gate.*'), '*' = everything
  active boolean not null default true,
  created_at timestamptz not null default now(),
  check (cardinality(events) between 1 and 50)
);
alter table public.webhooks enable row level security;
create policy "webhooks_manage_read" on public.webhooks for select to authenticated using (public.org_can(org_id, 'manage'));
create policy "webhooks_manage_insert" on public.webhooks for insert to authenticated with check (public.org_can(org_id, 'manage'));
create policy "webhooks_manage_update" on public.webhooks for update to authenticated
  using (public.org_can(org_id, 'manage')) with check (public.org_can(org_id, 'manage'));
create policy "webhooks_manage_delete" on public.webhooks for delete to authenticated using (public.org_can(org_id, 'manage'));

create table if not exists public.webhook_deliveries (
  id bigint generated always as identity primary key,
  webhook_id uuid not null references public.webhooks(id) on delete cascade,
  event text not null,
  payload jsonb not null,
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed')),
  attempts integer not null default 1,
  net_request_id bigint,                      -- pg_net request of the latest attempt
  response_status integer,
  next_attempt_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists webhook_deliveries_pending_idx on public.webhook_deliveries (status, next_attempt_at);
alter table public.webhook_deliveries enable row level security;
create policy "webhook_deliveries_manage_read" on public.webhook_deliveries for select to authenticated
  using (exists (select 1 from public.webhooks w where w.id = webhook_id and public.org_can(w.org_id, 'manage')));

create or replace function public.webhook_matches(p_events text[], p_action text)
returns boolean
language sql immutable set search_path = ''
as $$
  select exists (select 1 from unnest(p_events) e
                 where e = '*' or e = p_action or (right(e, 2) = '.*' and p_action like left(e, -1) || '%'));
$$;

-- Signs and sends one delivery now (pg_net is asynchronous: this only queues the request).
create or replace function public.send_webhook(p_delivery bigint)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  d public.webhook_deliveries;
  w public.webhooks;
  body text;
  request_id bigint;
begin
  select * into d from public.webhook_deliveries where id = p_delivery;
  select * into w from public.webhooks where id = d.webhook_id;
  body := d.payload::text;
  select net.http_post(
    url := w.url,
    body := d.payload,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'User-Agent', 'MarketingOS-Webhooks/1',
      'X-MarketingOS-Event', d.event,
      'X-MarketingOS-Delivery', d.id::text,
      'X-MarketingOS-Signature', 'sha256=' || encode(extensions.hmac(body, w.secret, 'sha256'), 'hex')
    ),
    timeout_milliseconds := 5000
  ) into request_id;
  update public.webhook_deliveries set net_request_id = request_id, updated_at = now() where id = d.id;
end;
$$;

-- Fan audit events out to matching webhooks.
create or replace function public.enqueue_webhooks()
returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
  w public.webhooks;
  delivery_id bigint;
begin
  if new.org_id is null then return null; end if;
  for w in select * from public.webhooks where org_id = new.org_id and active and public.webhook_matches(events, new.action) loop
    insert into public.webhook_deliveries (webhook_id, event, payload)
    values (w.id, new.action, jsonb_build_object(
      'id', new.id, 'event', new.action, 'created_at', new.created_at, 'organization_id', new.org_id,
      'actor', case when new.actor_type = 'system' then 'system' else new.actor_id::text end,
      'target', jsonb_build_object('type', new.target_type, 'id', new.target_id),
      'data', new.details))
    returning id into delivery_id;
    begin
      perform public.send_webhook(delivery_id);
    exception when others then
      -- Never let a webhook problem block the audited action; the sweep retries.
      update public.webhook_deliveries set next_attempt_at = now() where id = delivery_id;
    end;
  end loop;
  return null;
end;
$$;
drop trigger if exists audit_log_webhooks on public.audit_log;
create trigger audit_log_webhooks after insert on public.audit_log
  for each row execute function public.enqueue_webhooks();

-- A test event for one webhook (Settings → "Send test").
create or replace function public.ping_webhook(p_webhook uuid)
returns bigint
language plpgsql security definer set search_path = ''
as $$
declare
  w public.webhooks;
  delivery_id bigint;
begin
  select * into w from public.webhooks where id = p_webhook;
  if w.id is null or not public.org_can(w.org_id, 'manage') then raise exception 'not allowed'; end if;
  insert into public.webhook_deliveries (webhook_id, event, payload)
  values (w.id, 'ping', jsonb_build_object('event', 'ping', 'created_at', now(), 'organization_id', w.org_id))
  returning id into delivery_id;
  perform public.send_webhook(delivery_id);
  return delivery_id;
end;
$$;

-- Sweep helper: pg_net responses for in-flight deliveries.
create or replace function public.webhook_responses()
returns table (delivery_id bigint, status_code integer, timed_out boolean, error_msg text)
language sql stable security definer set search_path = ''
as $$
  select d.id, r.status_code, r.timed_out, r.error_msg
  from public.webhook_deliveries d join net._http_response r on r.id = d.net_request_id
  where d.status = 'pending';
$$;

revoke execute on function public.api_key_lookup(text, integer) from public, anon, authenticated;
revoke execute on function public.send_webhook(bigint) from public, anon, authenticated;
revoke execute on function public.webhook_responses() from public, anon, authenticated;
revoke execute on function public.enqueue_webhooks() from public, anon, authenticated;
grant execute on function public.api_key_lookup(text, integer), public.send_webhook(bigint), public.webhook_responses() to service_role;
revoke execute on function public.create_api_key(uuid, text, text[]), public.revoke_api_key(uuid), public.ping_webhook(uuid) from public, anon;
grant execute on function public.create_api_key(uuid, text, text[]), public.revoke_api_key(uuid), public.ping_webhook(uuid) to authenticated;

-- The api Edge Function checks plan limits before starting a campaign.
grant execute on function public.campaign_quota_reason(uuid) to service_role;
