-- GDPR: data export, account deletion, retention.
--
-- Export (Art. 15/20): export_my_data() returns everything personal to the
-- caller as one JSON document.
-- Erasure (Art. 17): the delete-account Edge Function calls
-- prepare_account_deletion() and then deletes the auth user; every personal
-- table cascades from auth.users. Campaigns the user created inside a team
-- organisation belong to that team, so they're handed to one of its owners
-- instead of being deleted. Deletion is refused while the user is the last
-- owner of a team that still has other members.
-- The audit log is kept (legitimate interest / legal obligation); it refers to
-- users only by id.
-- Retention: apply_retention() prunes operational data that isn't needed
-- forever; the hourly sweep runs it.

create or replace function public.export_my_data()
returns jsonb
language sql stable security definer set search_path = ''
as $$
  with me as (select auth.uid() as id),
  my_campaigns as (select c.* from public.campaigns c, me where c.user_id = me.id)
  select case when (select id from me) is null then null else jsonb_build_object(
    'exported_at', now(),
    'account', (select jsonb_build_object('id', u.id, 'email', u.email, 'created_at', u.created_at,
                  'username', u.raw_user_meta_data->>'username', 'last_sign_in_at', u.last_sign_in_at)
                from auth.users u, me where u.id = me.id),
    'subscription', (select to_jsonb(s) - 'user_id' from public.subscriptions s, me where s.user_id = me.id),
    'memberships', (select coalesce(jsonb_agg(jsonb_build_object('organization', o.name, 'personal', o.personal,
                      'role', m.role, 'joined_at', m.created_at)), '[]')
                    from public.memberships m join public.organizations o on o.id = m.org_id, me where m.user_id = me.id),
    'campaigns', (select coalesce(jsonb_agg(to_jsonb(c) || jsonb_build_object(
                    'personas', (select coalesce(jsonb_agg(to_jsonb(p) - 'user_id'), '[]') from public.personas p where p.campaign_id = c.id),
                    'rounds', (select coalesce(jsonb_agg(to_jsonb(i) - 'user_id'), '[]') from public.iterations i where i.campaign_id = c.id),
                    'metrics', (select coalesce(jsonb_agg(to_jsonb(x) - 'user_id'), '[]') from public.metrics x where x.campaign_id = c.id),
                    'feedback', (select coalesce(jsonb_agg(to_jsonb(f) - 'user_id'), '[]') from public.feedback f where f.campaign_id = c.id),
                    'gates', (select coalesce(jsonb_agg(to_jsonb(g) - 'user_id'), '[]') from public.gate_decisions g where g.campaign_id = c.id)
                  )), '[]') from my_campaigns c),
    'gate_votes', (select coalesce(jsonb_agg(to_jsonb(v) - 'user_id'), '[]') from public.gate_approvals v, me where v.user_id = me.id),
    'category_corrections', (select coalesce(jsonb_agg(to_jsonb(d) - 'user_id'), '[]') from public.domain_corrections d, me where d.user_id = me.id),
    'templates', (select coalesce(jsonb_agg(to_jsonb(t) - 'user_id'), '[]') from public.templates t, me where t.user_id = me.id),
    'provider_keys', (select coalesce(jsonb_agg(jsonb_build_object('capability', k.capability, 'masked_key', k.masked_key,
                        'updated_at', k.updated_at)), '[]') from public.provider_keys k, me where k.user_id = me.id),
    'tools_runs', (select coalesce(jsonb_agg(to_jsonb(r) - 'user_id'), '[]') from public.capability_runs r, me where r.user_id = me.id),
    'memory', (select coalesce(jsonb_agg(jsonb_build_object('content_type', e.content_type, 'content', e.content_text,
                 'campaign_id', e.campaign_id, 'outcome_reward', e.outcome_reward, 'created_at', e.created_at)), '[]')
               from public.embeddings e, me where e.user_id = me.id),
    'ai_usage', (select coalesce(jsonb_agg(to_jsonb(l) - 'user_id'), '[]') from public.llm_usage l, me where l.user_id = me.id),
    'audit_events', (select coalesce(jsonb_agg(jsonb_build_object('at', a.created_at, 'action', a.action,
                       'target_type', a.target_type, 'target_id', a.target_id, 'details', a.details) order by a.id), '[]')
                     from public.audit_log a, me where a.actor_id = me.id)
  ) end;
$$;
revoke execute on function public.export_my_data() from public, anon;
grant execute on function public.export_my_data() to authenticated;

-- Returns null when the account can be deleted, else why not (shown to the user).
create or replace function public.account_deletion_blocker(p_user uuid)
returns text
language sql stable security definer set search_path = ''
as $$
  select 'You are the only owner of "' || o.name || '", which has other members. Make someone else an owner, or remove the other members, first.'
  from public.memberships m join public.organizations o on o.id = m.org_id
  where m.user_id = p_user and m.role = 'owner' and not o.personal
    and not exists (select 1 from public.memberships x where x.org_id = o.id and x.role = 'owner' and x.user_id <> p_user)
    and exists (select 1 from public.memberships x where x.org_id = o.id and x.user_id <> p_user)
  limit 1;
$$;

-- Service role only (the delete-account Edge Function), right before the auth
-- user is deleted.
create or replace function public.prepare_account_deletion(p_user uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  blocker text := public.account_deletion_blocker(p_user);
  org record;
  heir uuid;
begin
  if blocker is not null then raise exception '%', blocker; end if;

  -- Team campaigns stay with the team: hand them to another owner (or admin).
  for org in
    select distinct c.org_id from public.campaigns c join public.organizations o on o.id = c.org_id
    where c.user_id = p_user and not o.personal
  loop
    select m.user_id into heir from public.memberships m
    where m.org_id = org.org_id and m.user_id <> p_user and m.role in ('owner', 'admin')
    order by (m.role = 'owner') desc, m.created_at limit 1;
    if heir is null then
      continue;  -- nobody left to inherit: the campaigns go with the account
    end if;
    update public.campaigns set user_id = heir where org_id = org.org_id and user_id = p_user;
    update public.personas p set user_id = heir from public.campaigns c where c.id = p.campaign_id and c.org_id = org.org_id and p.user_id = p_user;
    update public.iterations i set user_id = heir from public.campaigns c where c.id = i.campaign_id and c.org_id = org.org_id and i.user_id = p_user;
    update public.gate_decisions g set user_id = heir from public.campaigns c where c.id = g.campaign_id and c.org_id = org.org_id and g.user_id = p_user;
    update public.metrics x set user_id = heir from public.campaigns c where c.id = x.campaign_id and c.org_id = org.org_id and x.user_id = p_user;
    update public.feedback f set user_id = heir from public.campaigns c where c.id = f.campaign_id and c.org_id = org.org_id and f.user_id = p_user;
    perform public.audit(org.org_id, 'account.campaigns_transferred', 'user', p_user::text, jsonb_build_object('to', heir));
  end loop;

  -- Organisations where the user is the only member go with them (their
  -- campaigns cascade). Personal organisations always do.
  delete from public.organizations o
  where exists (select 1 from public.memberships m where m.org_id = o.id and m.user_id = p_user)
    and not exists (select 1 from public.memberships m where m.org_id = o.id and m.user_id <> p_user);

  perform public.audit(null, 'account.deleted', 'user', p_user::text, '{}'::jsonb);
end;
$$;
revoke execute on function public.prepare_account_deletion(uuid) from public, anon, authenticated;
revoke execute on function public.account_deletion_blocker(uuid) from public, anon;
grant execute on function public.prepare_account_deletion(uuid) to service_role;
grant execute on function public.account_deletion_blocker(uuid) to authenticated, service_role;

-- --- Retention ---------------------------------------------------------------

create or replace function public.apply_retention()
returns jsonb
language plpgsql security definer set search_path = ''
as $$
declare
  runs integer; usage integer; payloads integer; clicks integer;
begin
  -- Tools results are shown once; keep them 90 days.
  delete from public.capability_runs where created_at < now() - interval '90 days';
  get diagnostics runs = row_count;
  -- Per-call AI usage: 180 days covers billing disputes and trend charts.
  delete from public.llm_usage where created_at < now() - interval '180 days';
  get diagnostics usage = row_count;
  -- Delivered sends keep their outcome, but drop the payload (recipients,
  -- email HTML, image) after 30 days; failed/dead ones keep it for retries.
  update public.deliveries set payload = '{}'::jsonb
  where status in ('sent', 'dry_run') and payload <> '{}'::jsonb and updated_at < now() - interval '30 days';
  get diagnostics payloads = row_count;
  -- Raw click events: a year, after which metrics already hold the totals.
  delete from public.click_log where clicked_at < now() - interval '365 days';
  get diagnostics clicks = row_count;
  return jsonb_build_object('capability_runs', runs, 'llm_usage', usage, 'delivery_payloads', payloads, 'click_log', clicks);
end;
$$;
revoke execute on function public.apply_retention() from public, anon, authenticated;
grant execute on function public.apply_retention() to service_role;
