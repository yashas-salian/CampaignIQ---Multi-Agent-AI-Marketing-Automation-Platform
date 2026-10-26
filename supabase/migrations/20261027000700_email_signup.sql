-- Email engine, part 7: the brand's public sign-up form, with double opt-in.
--
-- /join/{slug} on the website: someone leaves their email, gets a confirmation
-- email (through the brand's own Resend account), and only clicking its link
-- makes them a subscriber, tagged "signed-up" (and "from:<campaign>" when they
-- came through a campaign's link). Links expire after 7 days. Someone already
-- subscribed gets nothing; someone who unsubscribed can come back this way
-- (and only this way); a spam complaint or an erasure is never undone. The form
-- is closed while email isn't connected, and politely past 110% of the plan's
-- contact cap. Each address may try 5 times an hour per brand.
--
-- The edge function (join) calls these as the service role; the page itself
-- only ever learns the brand's public name and look.

alter table public.contacts add column if not exists confirm_token_hash text;
alter table public.contacts add column if not exists confirm_expires_at timestamptz;
alter table public.contacts add column if not exists signup_campaign_id uuid references public.campaigns(id) on delete set null;
create unique index if not exists contacts_confirm_token_idx on public.contacts (confirm_token_hash) where confirm_token_hash is not null;

create table if not exists public.signup_attempts (
  id bigint generated always as identity primary key,
  org_id uuid not null references public.organizations(id) on delete cascade,
  ip_hash text not null,
  created_at timestamptz not null default now()
);
create index if not exists signup_attempts_recent_idx on public.signup_attempts (org_id, ip_hash, created_at desc);
alter table public.signup_attempts enable row level security;  -- workers only

-- Emails the engine sends that aren't campaign emails (confirmations): they count against the daily limit.
create table if not exists public.email_system_sends (
  id bigint generated always as identity primary key,
  org_id uuid not null references public.organizations(id) on delete cascade,
  kind text not null check (kind in ('confirmation')),
  sent_at timestamptz not null default now()
);
create index if not exists email_system_sends_org_idx on public.email_system_sends (org_id, sent_at desc);
alter table public.email_system_sends enable row level security;  -- workers only

create or replace function public.record_system_email(p_org uuid, p_kind text)
returns void language sql security definer set search_path = ''
as $$ insert into public.email_system_sends (org_id, kind) values (p_org, p_kind); $$;

create or replace function public.email_sent_today(p_org uuid)
returns integer
language sql stable security definer set search_path = ''
as $$
  select ((select count(*) filter (where not s.sandbox) + count(distinct s.resend_id) filter (where s.sandbox)
           from public.email_sends s join public.campaigns c on c.id::text = s.campaign_id
           where c.org_id = p_org and s.status in ('sent', 'delivered', 'bounced', 'complained')
             and s.sent_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc')
        + (select count(*) from public.email_system_sends y
           where y.org_id = p_org and y.sent_at >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'))::integer;
$$;

create or replace function public.signup_open(p_org uuid)
returns boolean language sql stable security definer set search_path = ''
as $$
  select exists (select 1 from public.org_email_settings where org_id = p_org)
     and (public.contact_cap(p_org) is null
          or (select count(*) from public.contacts where org_id = p_org) < ceil(public.contact_cap(p_org) * 1.1));
$$;

-- What the public form shows: the brand's name and look, and whether it's open.
create or replace function public.signup_info(p_slug text)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object('brand', o.name, 'slug', o.slug, 'privacy_url', k.privacy_url, 'brand_color', k.brand_color,
                            'logo_path', k.logo_path, 'open', public.signup_open(o.id))
  from public.organizations o left join public.brand_kits k on k.org_id = o.id
  where o.slug = lower(p_slug);
$$;

create or replace function public.new_confirmation(p_contact uuid)
returns text language plpgsql security definer set search_path = ''
as $$
declare
  token text := encode(extensions.gen_random_bytes(16), 'hex');
begin
  update public.contacts set confirm_token_hash = encode(extensions.digest(token, 'sha256'), 'hex'),
                             confirm_expires_at = now() + interval '7 days', updated_at = now()
   where id = p_contact;
  return token;
end;
$$;

-- A form submission. Returns {action, ...}: confirm_email (with the token and
-- what the email needs), already, blocked, closed, not_connected, rate_limited.
create or replace function public.signup_contact(
  p_slug text, p_email text, p_first_name text, p_language text, p_campaign uuid, p_consent_text text, p_ip text
)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  o public.organizations;
  addr text := lower(btrim(coalesce(p_email, '')));
  ip text := encode(extensions.digest(coalesce(p_ip, ''), 'sha256'), 'hex');
  x public.contacts;
  sup text;
  camp uuid;
begin
  select * into o from public.organizations where slug = lower(p_slug);
  if o.id is null then
    return jsonb_build_object('action', 'not_found');
  end if;
  if addr !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' or char_length(addr) > 254 then
    return jsonb_build_object('action', 'invalid');
  end if;
  if not exists (select 1 from public.org_email_settings where org_id = o.id) then
    return jsonb_build_object('action', 'not_connected');
  end if;
  if (select count(*) from public.signup_attempts where org_id = o.id and ip_hash = ip and created_at > now() - interval '1 hour') >= 5
     or (select count(*) from public.signup_attempts where org_id = o.id and created_at > now() - interval '1 hour') >= 300 then
    return jsonb_build_object('action', 'rate_limited');
  end if;
  insert into public.signup_attempts (org_id, ip_hash) values (o.id, ip);

  select reason into sup from public.email_suppressions where org_id = o.id and email_hash = public.email_hash(addr);
  if sup in ('complained', 'erased') then
    return jsonb_build_object('action', 'blocked');
  end if;
  camp := (select id from public.campaigns where id = p_campaign and org_id = o.id);
  select * into x from public.contacts where org_id = o.id and email = addr for update;
  if x.id is not null and x.status = 'subscribed' then
    return jsonb_build_object('action', 'already');
  end if;
  if x.id is null then
    if not public.signup_open(o.id) then
      return jsonb_build_object('action', 'closed');
    end if;
    insert into public.contacts (org_id, email, first_name, language, status, consent_source, consent_text, signup_campaign_id)
    values (o.id, addr, nullif(left(btrim(p_first_name), 80), ''), case when p_language ~ '^[a-z]{2}$' then p_language end,
            'pending', 'signup_form', left(btrim(coalesce(p_consent_text, 'Signed up on the brand''s form')), 1000), camp)
    returning * into x;
    insert into public.contact_events (org_id, contact_id, kind, actor, details)
    values (o.id, x.id, 'subscribed', 'contact', jsonb_build_object('source', 'signup_form', 'campaign', camp, 'awaiting', 'confirmation'));
  else
    -- Pending again, or coming back after unsubscribing / bouncing: nothing changes until they confirm.
    update public.contacts set first_name = coalesce(nullif(left(btrim(p_first_name), 80), ''), first_name),
                               signup_campaign_id = coalesce(camp, signup_campaign_id),
                               consent_text = left(btrim(coalesce(p_consent_text, consent_text)), 1000), updated_at = now()
     where id = x.id;
  end if;
  return jsonb_build_object('action', 'confirm_email', 'token', public.new_confirmation(x.id), 'email', addr, 'org_id', o.id,
                            'first_name', coalesce(nullif(btrim(p_first_name), ''), x.first_name),
                            'language', coalesce(case when p_language ~ '^[a-z]{2}$' then p_language end, x.language, 'en'));
end;
$$;

-- The confirmation link: subscribed from now on (lifting an earlier unsubscribe), tagged.
create or replace function public.confirm_contact(p_token text)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  x public.contacts;
  camp_idea text;
  new_tags jsonb := '["signed-up"]'::jsonb;
begin
  select * into x from public.contacts
  where confirm_token_hash = encode(extensions.digest(coalesce(p_token, ''), 'sha256'), 'hex');
  if x.id is null then
    return null;
  end if;
  if x.status = 'subscribed' then
    return jsonb_build_object('status', 'subscribed', 'brand', (select name from public.organizations where id = x.org_id));
  end if;
  if x.confirm_expires_at < now() then
    return null;
  end if;
  if exists (select 1 from public.email_suppressions where org_id = x.org_id and email_hash = public.email_hash(x.email)
             and reason in ('complained', 'erased')) then
    return null;
  end if;
  camp_idea := (select c.idea from public.campaigns c where c.id = x.signup_campaign_id);
  if camp_idea is not null then
    new_tags := new_tags || to_jsonb('from:' || left(btrim(regexp_replace(lower(camp_idea), '[^a-z0-9]+', '-', 'g'), '-'), 30));
  end if;
  update public.contacts set status = 'subscribed', confirmed_at = now(), consent_source = 'signup_form', consent_at = now(),
                             soft_bounces = 0, tags = public.merge_tags(x.tags, new_tags), updated_at = now()
   where id = x.id;
  delete from public.email_suppressions where org_id = x.org_id and email_hash = public.email_hash(x.email)
    and reason in ('unsubscribed', 'bounced');
  insert into public.contact_events (org_id, contact_id, kind, actor, details)
  values (x.org_id, x.id, case when x.status = 'pending' then 'confirmed' else 'resubscribed' end, 'contact',
          jsonb_build_object('campaign', x.signup_campaign_id));
  return jsonb_build_object('status', 'subscribed', 'brand', (select name from public.organizations where id = x.org_id));
end;
$$;

-- "Resubscribe" on the unsubscribe page: a fresh confirmation for that person.
create or replace function public.resubscribe_by_token(p_token text)
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  x public.contacts;
begin
  select c.* into x from public.campaign_audience ca join public.contacts c on c.id = ca.contact_id where ca.unsub_token = p_token;
  if x.id is null then
    return null;
  end if;
  if exists (select 1 from public.email_suppressions where org_id = x.org_id and email_hash = public.email_hash(x.email)
             and reason in ('complained', 'erased')) then
    return jsonb_build_object('action', 'blocked');
  end if;
  if x.status = 'subscribed' then
    return jsonb_build_object('action', 'already');
  end if;
  if not exists (select 1 from public.org_email_settings where org_id = x.org_id) then
    return jsonb_build_object('action', 'not_connected');
  end if;
  return jsonb_build_object('action', 'confirm_email', 'token', public.new_confirmation(x.id), 'email', x.email, 'org_id', x.org_id,
                            'first_name', x.first_name, 'language', coalesce(x.language, 'en'));
end;
$$;

do $$
declare
  fn text;
begin
  foreach fn in array array['record_system_email(uuid, text)', 'email_sent_today(uuid)', 'signup_open(uuid)', 'signup_info(text)',
                            'new_confirmation(uuid)', 'signup_contact(text, text, text, text, uuid, text, text)',
                            'confirm_contact(text)', 'resubscribe_by_token(text)']
  loop
    execute format('revoke execute on function public.%s from public, anon, authenticated', fn);
    execute format('grant execute on function public.%s to service_role', fn);
  end loop;
end $$;

-- Campaign posts (Bluesky, Mastodon, Reddit) end with the brand's sign-up link
-- while email is connected; one switch per campaign turns it off.
alter table public.campaigns add column if not exists signup_link boolean not null default true;

create or replace function public.set_campaign_signup_link(p_campaign uuid, p_on boolean)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  org uuid := (select org_id from public.campaigns where id = p_campaign);
begin
  if org is null or not public.org_can(org, 'create') then
    raise exception 'only owners, admins and marketers can change this campaign';
  end if;
  update public.campaigns set signup_link = coalesce(p_on, true), updated_at = now() where id = p_campaign;
end;
$$;
revoke execute on function public.set_campaign_signup_link(uuid, boolean) from public, anon;
grant execute on function public.set_campaign_signup_link(uuid, boolean) to authenticated;

-- What the worker needs to add the link to a campaign's posts.
create or replace function public.campaign_signup_link(p_campaign uuid)
returns jsonb
language sql stable security definer set search_path = ''
as $$
  select jsonb_build_object('slug', o.slug, 'language', c.target_language)
  from public.campaigns c join public.organizations o on o.id = c.org_id
  where c.id = p_campaign and c.signup_link and exists (select 1 from public.org_email_settings e where e.org_id = c.org_id);
$$;
revoke execute on function public.campaign_signup_link(uuid) from public, anon, authenticated;
grant execute on function public.campaign_signup_link(uuid) to service_role;
