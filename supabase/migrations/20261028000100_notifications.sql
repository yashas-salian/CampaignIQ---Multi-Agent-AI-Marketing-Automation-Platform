-- Notifications: the people who must act hear about it, in the app and by email.
--
-- When a gate is waiting for approval (or one is overdue, a campaign is held,
-- email is paused...) the worker calls notification_recipients() for the
-- organisation's designated approvers, or its owners and admins, writes each
-- person an in-app notification (notify_users) and emails those who haven't
-- turned email off. Managers choose who the approvers to notify are
-- (org_settings.notify_user_ids); none chosen means everyone who can approve.

alter table public.org_settings add column if not exists notify_user_ids uuid[] not null default '{}';

create table if not exists public.notifications (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  org_id uuid not null references public.organizations(id) on delete cascade,
  kind text not null check (char_length(kind) <= 40),
  title text not null check (char_length(title) <= 200),
  body text check (char_length(body) <= 1000),
  link text check (link is null or link ~ '^/'),
  campaign_id uuid references public.campaigns(id) on delete cascade,
  created_at timestamptz not null default now(),
  read_at timestamptz
);
create index if not exists notifications_user_idx on public.notifications (user_id, created_at desc);
alter table public.notifications enable row level security;
create policy "notifications_own_read" on public.notifications for select to authenticated using (user_id = auth.uid());

create table if not exists public.notification_prefs (
  user_id uuid primary key references auth.users(id) on delete cascade,
  email boolean not null default true,
  updated_at timestamptz not null default now()
);
alter table public.notification_prefs enable row level security;
create policy "notification_prefs_own_read" on public.notification_prefs for select to authenticated using (user_id = auth.uid());

-- Who to tell. audience 'approvers': the designated approvers who can still
-- approve (or, if none of them can, everyone who can approve); 'managers': owners and admins.
create or replace function public.notification_recipients(p_org uuid, p_audience text)
returns table (user_id uuid, email text, email_on boolean)
language sql stable security definer set search_path = ''
as $$
  select m.user_id, u.email::text, coalesce(p.email, true)
  from public.memberships m
  join auth.users u on u.id = m.user_id
  left join public.notification_prefs p on p.user_id = m.user_id
  left join public.org_settings s on s.org_id = m.org_id
  where m.org_id = p_org
    and case p_audience
          when 'managers' then public.role_can(m.role, 'manage')
          else public.role_can(m.role, 'approve')
               and (m.user_id = any(coalesce(s.notify_user_ids, '{}'))
                    or not exists (select 1 from public.memberships d
                                   where d.org_id = p_org and public.role_can(d.role, 'approve')
                                     and d.user_id = any(coalesce(s.notify_user_ids, '{}'))))
        end
  order by m.created_at;
$$;

create or replace function public.notify_users(p_org uuid, p_users uuid[], p_kind text, p_title text, p_body text, p_link text,
                                               p_campaign uuid)
returns integer
language sql security definer set search_path = ''
as $$
  with ins as (
    insert into public.notifications (user_id, org_id, kind, title, body, link, campaign_id)
    select u, p_org, p_kind, left(p_title, 200), left(p_body, 1000), p_link, p_campaign
    from unnest(p_users) u
    where exists (select 1 from public.memberships m where m.org_id = p_org and m.user_id = u)
    returning 1)
  select count(*)::integer from ins;
$$;

create or replace function public.set_notification_people(p_org uuid, p_users uuid[])
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  if not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can choose who is notified';
  end if;
  -- Only people here who can approve are kept: someone who has left or changed
  -- role is dropped, so a stale list never blocks saving the approval policy.
  select coalesce(array_agg(m.user_id), '{}') into p_users
  from public.memberships m
  where m.org_id = p_org and public.role_can(m.role, 'approve') and m.user_id = any(coalesce(p_users, '{}'));
  insert into public.org_settings (org_id, notify_user_ids, updated_at) values (p_org, p_users, now())
  on conflict (org_id) do update set notify_user_ids = excluded.notify_user_ids, updated_at = now();
  perform public.audit(p_org, 'notifications.people', 'organization', p_org::text, jsonb_build_object('people', cardinality(p_users)));
end;
$$;

create or replace function public.set_notification_email(p_on boolean)
returns void
language sql security definer set search_path = ''
as $$
  insert into public.notification_prefs (user_id, email, updated_at) values (auth.uid(), coalesce(p_on, true), now())
  on conflict (user_id) do update set email = excluded.email, updated_at = now();
$$;

create or replace function public.mark_notifications_read(p_ids bigint[])
returns integer
language sql security definer set search_path = ''
as $$
  with upd as (
    update public.notifications set read_at = now()
    where user_id = auth.uid() and read_at is null and (p_ids is null or id = any(p_ids))
    returning 1)
  select count(*)::integer from upd;
$$;

revoke execute on function public.notification_recipients(uuid, text) from public, anon, authenticated;
grant execute on function public.notification_recipients(uuid, text) to service_role;
revoke execute on function public.notify_users(uuid, uuid[], text, text, text, text, uuid) from public, anon, authenticated;
grant execute on function public.notify_users(uuid, uuid[], text, text, text, text, uuid) to service_role;
revoke execute on function public.set_notification_people(uuid, uuid[]) from public, anon;
revoke execute on function public.set_notification_email(boolean) from public, anon;
revoke execute on function public.mark_notifications_read(bigint[]) from public, anon;
grant execute on function public.set_notification_people(uuid, uuid[]), public.set_notification_email(boolean),
  public.mark_notifications_read(bigint[]) to authenticated;

alter publication supabase_realtime add table public.notifications;
