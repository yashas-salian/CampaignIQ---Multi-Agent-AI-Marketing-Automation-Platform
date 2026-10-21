-- Organisations, roles and invitations.
--
-- Campaigns now belong to an organisation, and access follows the caller's
-- role in it instead of "rows I created":
--
--   permission   owner admin marketer approver viewer
--   view           x     x      x        x       x
--   create         x     x      x                      create / run / stop campaigns
--   approve        x     x               x              gate decisions, persona + category picks
--   manage         x     x                             members, invitations, org settings
--   own            x                                  delete the org, grant ownership
--
-- Marketers can't approve their own campaigns (separation of duties).
-- Every user gets a personal organisation (they're its owner), so solo use
-- works exactly as before; existing campaigns are moved into their creator's
-- personal org. Membership changes only happen through the checked functions
-- at the bottom (no direct write policies), which guard the last owner.

create table if not exists public.organizations (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 1 and 80),
  personal boolean not null default false,
  created_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now()
);

create table if not exists public.memberships (
  org_id uuid not null references public.organizations(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  role text not null check (role in ('owner', 'admin', 'marketer', 'approver', 'viewer')),
  created_at timestamptz not null default now(),
  primary key (org_id, user_id)
);
create index if not exists memberships_user_idx on public.memberships (user_id);

create table if not exists public.invitations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations(id) on delete cascade,
  email text not null check (email = lower(email) and position('@' in email) > 1),
  role text not null check (role in ('admin', 'marketer', 'approver', 'viewer')),
  token_hash text not null unique,      -- sha256 of the invite token; the token itself is never stored
  invited_by uuid references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '7 days',
  accepted_at timestamptz,
  accepted_by uuid references auth.users(id) on delete set null
);
create index if not exists invitations_org_idx on public.invitations (org_id);

-- --- Permission helpers (SECURITY DEFINER: they read memberships without
-- tripping over memberships' own RLS) ---------------------------------------

create or replace function public.org_role(p_org uuid)
returns text
language sql stable security definer set search_path = ''
as $$
  select role from public.memberships where org_id = p_org and user_id = auth.uid();
$$;

create or replace function public.role_can(p_role text, p_permission text)
returns boolean
language sql immutable set search_path = ''
as $$
  select case p_permission
    when 'view' then p_role in ('owner', 'admin', 'marketer', 'approver', 'viewer')
    when 'create' then p_role in ('owner', 'admin', 'marketer')
    when 'approve' then p_role in ('owner', 'admin', 'approver')
    when 'manage' then p_role in ('owner', 'admin')
    when 'own' then p_role = 'owner'
    else false
  end;
$$;

create or replace function public.org_can(p_org uuid, p_permission text)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select coalesce(public.role_can(public.org_role(p_org), p_permission), false);
$$;

-- --- Personal organisations: backfill, and one for every new signup ------

create or replace function public.ensure_personal_org(p_user uuid)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  org uuid;
begin
  select m.org_id into org
  from public.memberships m join public.organizations o on o.id = m.org_id
  where m.user_id = p_user and o.personal and m.role = 'owner'
  limit 1;
  if org is null then
    insert into public.organizations (name, personal, created_by) values ('Personal', true, p_user) returning id into org;
    insert into public.memberships (org_id, user_id, role) values (org, p_user, 'owner');
  end if;
  return org;
end;
$$;

do $$
declare u record;
begin
  for u in select id from auth.users loop
    perform public.ensure_personal_org(u.id);
  end loop;
end $$;

create or replace function public.handle_new_user()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.subscriptions (user_id, status) values (new.id, 'free') on conflict do nothing;
  perform public.ensure_personal_org(new.id);
  return new;
end;
$$;

-- --- Campaigns belong to an organisation ---------------------------------

alter table public.campaigns add column if not exists org_id uuid references public.organizations(id) on delete cascade;
update public.campaigns c set org_id = public.ensure_personal_org(c.user_id) where c.org_id is null;
alter table public.campaigns alter column org_id set not null;
create index if not exists campaigns_org_idx on public.campaigns (org_id, created_at desc);

create or replace function public.campaign_can(p_campaign uuid, p_permission text)
returns boolean
language sql stable security definer set search_path = ''
as $$
  select coalesce((select public.org_can(c.org_id, p_permission) from public.campaigns c where c.id = p_campaign), false);
$$;

-- Callers that don't pass an org (older workers) get the creator's personal one.
create or replace function public.default_campaign_org()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  if new.org_id is null then
    new.org_id := public.ensure_personal_org(new.user_id);
  end if;
  return new;
end;
$$;
drop trigger if exists campaigns_default_org on public.campaigns;
create trigger campaigns_default_org before insert on public.campaigns
  for each row execute function public.default_campaign_org();

-- --- Policies: organisation + permission instead of row ownership --------

alter table public.organizations enable row level security;
alter table public.memberships enable row level security;
alter table public.invitations enable row level security;

create policy "organizations_member_read" on public.organizations for select to authenticated using (public.org_can(id, 'view'));
create policy "organizations_manage_update" on public.organizations for update to authenticated
  using (public.org_can(id, 'manage')) with check (public.org_can(id, 'manage'));
create policy "memberships_member_read" on public.memberships for select to authenticated using (public.org_can(org_id, 'view'));
create policy "invitations_manage_read" on public.invitations for select to authenticated using (public.org_can(org_id, 'manage'));
create policy "invitations_manage_delete" on public.invitations for delete to authenticated using (public.org_can(org_id, 'manage'));

drop policy if exists "campaigns_owner" on public.campaigns;
create policy "campaigns_read" on public.campaigns for select to authenticated using (public.org_can(org_id, 'view'));
create policy "campaigns_insert" on public.campaigns for insert to authenticated
  with check (public.org_can(org_id, 'create') and user_id = auth.uid());
create policy "campaigns_update" on public.campaigns for update to authenticated
  using (public.org_can(org_id, 'create') or public.org_can(org_id, 'approve'))
  with check (public.org_can(org_id, 'create') or public.org_can(org_id, 'approve'));
create policy "campaigns_delete" on public.campaigns for delete to authenticated using (public.org_can(org_id, 'manage'));

drop policy if exists "personas_owner" on public.personas;
create policy "personas_read" on public.personas for select to authenticated using (public.campaign_can(campaign_id, 'view'));
create policy "personas_pick" on public.personas for update to authenticated
  using (public.campaign_can(campaign_id, 'approve')) with check (public.campaign_can(campaign_id, 'approve'));

drop policy if exists "iterations_owner" on public.iterations;
create policy "iterations_read" on public.iterations for select to authenticated using (public.campaign_can(campaign_id, 'view'));

drop policy if exists "gate_decisions_owner" on public.gate_decisions;
create policy "gate_decisions_read" on public.gate_decisions for select to authenticated using (public.campaign_can(campaign_id, 'view'));
create policy "gate_decisions_decide" on public.gate_decisions for update to authenticated
  using (public.campaign_can(campaign_id, 'approve')) with check (public.campaign_can(campaign_id, 'approve'));

drop policy if exists "metrics_owner" on public.metrics;
create policy "metrics_read" on public.metrics for select to authenticated using (public.campaign_can(campaign_id, 'view'));

drop policy if exists "feedback_owner" on public.feedback;
create policy "feedback_read" on public.feedback for select to authenticated using (public.campaign_can(campaign_id, 'view'));

drop policy if exists "domain_corrections_owner_select" on public.domain_corrections;
drop policy if exists "domain_corrections_owner_insert" on public.domain_corrections;
create policy "domain_corrections_read" on public.domain_corrections for select to authenticated using (public.campaign_can(campaign_id, 'view'));
create policy "domain_corrections_insert" on public.domain_corrections for insert to authenticated
  with check (public.campaign_can(campaign_id, 'approve') and user_id = auth.uid());

drop policy if exists "deliveries_owner_read" on public.deliveries;
create policy "deliveries_read" on public.deliveries for select to authenticated using (
  user_id = auth.uid()
  or exists (select 1 from public.campaigns c where c.id::text = deliveries.campaign_id and public.org_can(c.org_id, 'view'))
);

-- --- Membership management (the only way memberships change) ------------

create or replace function public.create_organization(p_name text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare org uuid;
begin
  if auth.uid() is null then raise exception 'sign in first'; end if;
  insert into public.organizations (name, created_by) values (trim(p_name), auth.uid()) returning id into org;
  insert into public.memberships (org_id, user_id, role) values (org, auth.uid(), 'owner');
  return org;
end;
$$;

-- Returns the raw invite token once; only its hash is stored.
create or replace function public.create_invitation(p_org uuid, p_email text, p_role text)
returns text
language plpgsql security definer set search_path = ''
as $$
declare token text := encode(extensions.gen_random_bytes(24), 'hex');
begin
  if not public.org_can(p_org, 'manage') then raise exception 'not allowed: managing members needs admin or owner'; end if;
  if p_role = 'admin' and not public.org_can(p_org, 'own') then raise exception 'only owners can invite admins'; end if;
  if (select personal from public.organizations where id = p_org) then raise exception 'personal organisations cannot have members; create a team organisation'; end if;
  insert into public.invitations (org_id, email, role, token_hash, invited_by)
  values (p_org, lower(trim(p_email)), p_role, encode(extensions.digest(token, 'sha256'), 'hex'), auth.uid());
  return token;
end;
$$;

create or replace function public.accept_invitation(p_token text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  inv public.invitations;
  me text := (select lower(email) from auth.users where id = auth.uid());
begin
  select * into inv from public.invitations
  where token_hash = encode(extensions.digest(p_token, 'sha256'), 'hex')
  for update;
  if inv.id is null or inv.accepted_at is not null or inv.expires_at < now() then
    raise exception 'this invitation is invalid, expired or already used';
  end if;
  if inv.email <> me then raise exception 'this invitation was sent to a different email address'; end if;
  insert into public.memberships (org_id, user_id, role) values (inv.org_id, auth.uid(), inv.role)
  on conflict (org_id, user_id) do update set role = excluded.role
    where public.memberships.role <> 'owner';  -- never downgrade an owner through an invite
  update public.invitations set accepted_at = now(), accepted_by = auth.uid() where id = inv.id;
  return inv.org_id;
end;
$$;

create or replace function public.set_member_role(p_org uuid, p_user uuid, p_role text)
returns void
language plpgsql security definer set search_path = ''
as $$
declare v_role text := (select role from public.memberships where org_id = p_org and user_id = p_user);
begin
  if not public.org_can(p_org, 'manage') then raise exception 'not allowed: managing members needs admin or owner'; end if;
  if v_role is null then raise exception 'not a member'; end if;
  if p_role not in ('owner', 'admin', 'marketer', 'approver', 'viewer') then raise exception 'unknown role %', p_role; end if;
  if (p_role in ('owner', 'admin') or v_role in ('owner', 'admin')) and not public.org_can(p_org, 'own') then
    raise exception 'only owners can grant or change owner and admin roles';
  end if;
  if v_role = 'owner' and p_role <> 'owner'
     and (select count(*) from public.memberships where org_id = p_org and role = 'owner') = 1 then
    raise exception 'an organisation needs at least one owner';
  end if;
  update public.memberships set role = p_role where org_id = p_org and user_id = p_user;
end;
$$;

create or replace function public.remove_member(p_org uuid, p_user uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare target_role text := (select role from public.memberships where org_id = p_org and user_id = p_user);
begin
  if p_user <> auth.uid() and not public.org_can(p_org, 'manage') then raise exception 'not allowed'; end if;
  if target_role in ('owner', 'admin') and p_user <> auth.uid() and not public.org_can(p_org, 'own') then
    raise exception 'only owners can remove owners and admins';
  end if;
  if target_role = 'owner' and (select count(*) from public.memberships where org_id = p_org and role = 'owner') = 1 then
    raise exception 'an organisation needs at least one owner';
  end if;
  delete from public.memberships where org_id = p_org and user_id = p_user;
end;
$$;

-- Member list with emails (auth.users isn't readable by clients).
create or replace function public.org_members(p_org uuid)
returns table (user_id uuid, role text, email text, username text, joined_at timestamptz)
language sql stable security definer set search_path = ''
as $$
  select m.user_id, m.role, u.email::text, u.raw_user_meta_data->>'username', m.created_at
  from public.memberships m join auth.users u on u.id = m.user_id
  where m.org_id = p_org and public.org_can(p_org, 'view')
  order by m.created_at;
$$;

revoke execute on function public.ensure_personal_org(uuid) from public, anon, authenticated;
grant execute on function public.ensure_personal_org(uuid) to service_role;
revoke execute on function public.create_organization(text) from public, anon;
revoke execute on function public.create_invitation(uuid, text, text) from public, anon;
revoke execute on function public.accept_invitation(text) from public, anon;
revoke execute on function public.set_member_role(uuid, uuid, text) from public, anon;
revoke execute on function public.remove_member(uuid, uuid) from public, anon;
revoke execute on function public.org_members(uuid) from public, anon;
grant execute on function public.create_organization(text), public.create_invitation(uuid, text, text),
  public.accept_invitation(text), public.set_member_role(uuid, uuid, text), public.remove_member(uuid, uuid),
  public.org_members(uuid) to authenticated, service_role;

alter publication supabase_realtime add table public.memberships;
