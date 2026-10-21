-- Tamper-evident audit log.
--
-- Written by database triggers, so no code path (frontend, workers, Edge
-- Functions, SQL editor) can skip it. Every row carries the hash of the row
-- before it: changing or deleting history breaks the chain, and
-- verify_audit_chain() reports the first row where it breaks. The table is
-- append-only for every role, including the service role.
-- Never logged: secrets, key material, invite tokens, delivery payloads.

create table if not exists public.audit_log (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default clock_timestamp(),
  org_id uuid,                -- no FK: the trail must outlive a deleted organisation
  actor_id uuid,              -- auth.uid(); null for workers and system jobs
  actor_type text not null check (actor_type in ('user', 'system')),
  action text not null,       -- e.g. campaign.created, gate.decided, membership.role_changed
  target_type text not null,
  target_id text,
  details jsonb not null default '{}'::jsonb,
  prev_hash text,
  hash text not null
);
create index if not exists audit_log_org_idx on public.audit_log (org_id, id desc);
create index if not exists audit_log_actor_idx on public.audit_log (actor_id, id desc);

-- Chain each row to the previous one (timestamps hashed in a fixed UTC format,
-- so verification doesn't depend on the session's time zone). The advisory lock serialises writers so
-- two concurrent inserts can't both claim the same predecessor.
create or replace function public.audit_log_chain()
returns trigger
language plpgsql security definer set search_path = ''
as $$
begin
  perform pg_advisory_xact_lock(hashtext('public.audit_log'));
  select hash into new.prev_hash from public.audit_log order by id desc limit 1;
  new.hash := encode(extensions.digest(
    coalesce(new.prev_hash, '') || '|' || new.id || '|' || to_char(new.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|' || coalesce(new.org_id::text, '') || '|' ||
    coalesce(new.actor_id::text, '') || '|' || new.actor_type || '|' || new.action || '|' || new.target_type || '|' ||
    coalesce(new.target_id, '') || '|' || new.details::text,
    'sha256'), 'hex');
  return new;
end;
$$;
drop trigger if exists audit_log_chain on public.audit_log;
create trigger audit_log_chain before insert on public.audit_log for each row execute function public.audit_log_chain();

create or replace function public.audit_log_append_only()
returns trigger
language plpgsql set search_path = ''
as $$
begin
  raise exception 'audit_log is append-only';
end;
$$;
drop trigger if exists audit_log_no_update on public.audit_log;
create trigger audit_log_no_update before update or delete on public.audit_log
  for each row execute function public.audit_log_append_only();
drop trigger if exists audit_log_no_truncate on public.audit_log;
create trigger audit_log_no_truncate before truncate on public.audit_log
  for each statement execute function public.audit_log_append_only();

revoke insert, update, delete, truncate on public.audit_log from anon, authenticated, service_role;

-- Returns the id of the first row whose hash doesn't match (null = intact).
create or replace function public.verify_audit_chain()
returns bigint
language plpgsql stable security definer set search_path = ''
as $$
declare
  r public.audit_log;
  expected_prev text := null;
begin
  for r in select * from public.audit_log order by id loop
    if r.prev_hash is distinct from expected_prev or r.hash <> encode(extensions.digest(
         coalesce(r.prev_hash, '') || '|' || r.id || '|' || to_char(r.created_at at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US') || '|' || coalesce(r.org_id::text, '') || '|' ||
         coalesce(r.actor_id::text, '') || '|' || r.actor_type || '|' || r.action || '|' || r.target_type || '|' ||
         coalesce(r.target_id, '') || '|' || r.details::text,
         'sha256'), 'hex') then
      return r.id;
    end if;
    expected_prev := r.hash;
  end loop;
  return null;
end;
$$;
revoke execute on function public.verify_audit_chain() from public, anon, authenticated;
grant execute on function public.verify_audit_chain() to service_role;

-- The single writer used by every trigger below.
create or replace function public.audit(
  p_org uuid, p_action text, p_target_type text, p_target_id text, p_details jsonb default '{}'::jsonb
)
returns void
language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.audit_log (org_id, actor_id, actor_type, action, target_type, target_id, details)
  values (p_org, auth.uid(), case when auth.uid() is null then 'system' else 'user' end,
          p_action, p_target_type, p_target_id, coalesce(p_details, '{}'::jsonb));
end;
$$;
revoke execute on function public.audit(uuid, text, text, text, jsonb) from public, anon, authenticated;

-- Changed columns as {"col": [old, new]}, minus noise and anything sensitive.
create or replace function public.audit_changes(p_old jsonb, p_new jsonb, p_skip text[])
returns jsonb
language sql immutable set search_path = ''
as $$
  select coalesce(jsonb_object_agg(key, jsonb_build_array(p_old -> key, p_new -> key)), '{}'::jsonb)
  from jsonb_object_keys(p_new) as key
  where key <> all (p_skip) and (p_old -> key) is distinct from (p_new -> key);
$$;

-- --- Triggers ---------------------------------------------------------------

create or replace function public.audit_campaigns()
returns trigger language plpgsql security definer set search_path = '' as $$
declare changes jsonb;
begin
  if tg_op = 'INSERT' then
    perform public.audit(new.org_id, 'campaign.created', 'campaign', new.id::text,
      jsonb_build_object('idea', left(new.idea, 200), 'domain_category', new.domain_category, 'created_by', new.user_id));
  elsif tg_op = 'UPDATE' then
    changes := public.audit_changes(to_jsonb(old), to_jsonb(new),
      array['updated_at', 'campaign_summary', 'feasibility_rationale', 'current_round', 'distributed_at']);
    if changes ? 'status' then
      perform public.audit(new.org_id, 'campaign.status_changed', 'campaign', new.id::text, changes -> 'status');
    end if;
    if changes ? 'stop_requested' then
      perform public.audit(new.org_id, 'campaign.stop_requested', 'campaign', new.id::text, '{}'::jsonb);
    end if;
    if changes ? 'domain_category' then
      perform public.audit(new.org_id, 'campaign.category_corrected', 'campaign', new.id::text, changes -> 'domain_category');
    end if;
  else
    perform public.audit(old.org_id, 'campaign.deleted', 'campaign', old.id::text, jsonb_build_object('idea', left(old.idea, 200)));
  end if;
  return null;
end; $$;
drop trigger if exists audit_campaigns on public.campaigns;
create trigger audit_campaigns after insert or update or delete on public.campaigns
  for each row execute function public.audit_campaigns();

create or replace function public.audit_gate_decisions()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.decision is not null and old.decision is distinct from new.decision then
    perform public.audit((select org_id from public.campaigns where id = new.campaign_id), 'gate.decided', 'campaign',
      new.campaign_id::text, jsonb_build_object('gate', new.gate_number, 'round', new.round_number,
      'decision', new.decision, 'comment', left(new.comment, 500)));
  end if;
  return null;
end; $$;
drop trigger if exists audit_gate_decisions on public.gate_decisions;
create trigger audit_gate_decisions after update on public.gate_decisions
  for each row execute function public.audit_gate_decisions();

create or replace function public.audit_memberships()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    perform public.audit(new.org_id, 'membership.added', 'user', new.user_id::text, jsonb_build_object('role', new.role));
  elsif tg_op = 'UPDATE' and old.role is distinct from new.role then
    perform public.audit(new.org_id, 'membership.role_changed', 'user', new.user_id::text, jsonb_build_array(old.role, new.role));
  elsif tg_op = 'DELETE' then
    perform public.audit(old.org_id, 'membership.removed', 'user', old.user_id::text, jsonb_build_object('role', old.role));
  end if;
  return null;
end; $$;
drop trigger if exists audit_memberships on public.memberships;
create trigger audit_memberships after insert or update or delete on public.memberships
  for each row execute function public.audit_memberships();

create or replace function public.audit_invitations()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' then
    perform public.audit(new.org_id, 'invitation.created', 'invitation', new.id::text,
      jsonb_build_object('email', new.email, 'role', new.role));
  elsif tg_op = 'UPDATE' and old.accepted_at is null and new.accepted_at is not null then
    perform public.audit(new.org_id, 'invitation.accepted', 'invitation', new.id::text,
      jsonb_build_object('email', new.email, 'role', new.role));
  elsif tg_op = 'DELETE' and old.accepted_at is null then
    perform public.audit(old.org_id, 'invitation.revoked', 'invitation', old.id::text, jsonb_build_object('email', old.email));
  end if;
  return null;
end; $$;
drop trigger if exists audit_invitations on public.invitations;
create trigger audit_invitations after insert or update or delete on public.invitations
  for each row execute function public.audit_invitations();

create or replace function public.audit_organizations()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'INSERT' and not new.personal then
    perform public.audit(new.id, 'organization.created', 'organization', new.id::text, jsonb_build_object('name', new.name));
  elsif tg_op = 'UPDATE' and old.name is distinct from new.name then
    perform public.audit(new.id, 'organization.renamed', 'organization', new.id::text, jsonb_build_array(old.name, new.name));
  end if;
  return null;
end; $$;
drop trigger if exists audit_organizations on public.organizations;
create trigger audit_organizations after insert or update on public.organizations
  for each row execute function public.audit_organizations();

-- BYOK keys: who changed which capability's key; never the key itself.
create or replace function public.audit_provider_keys()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if tg_op = 'DELETE' then
    perform public.audit(null, 'provider_key.deleted', 'user', old.user_id::text, jsonb_build_object('capability', old.capability));
  else
    perform public.audit(null, case when tg_op = 'INSERT' then 'provider_key.added' else 'provider_key.rotated' end,
      'user', new.user_id::text, jsonb_build_object('capability', new.capability, 'masked', new.masked_key));
  end if;
  return null;
end; $$;
drop trigger if exists audit_provider_keys on public.provider_keys;
create trigger audit_provider_keys after insert or update or delete on public.provider_keys
  for each row execute function public.audit_provider_keys();

-- Outbound sends: what left the building, and what gave up.
create or replace function public.audit_deliveries()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if new.status in ('sent', 'dead') and old.status is distinct from new.status then
    perform public.audit((select org_id from public.campaigns where id::text = new.campaign_id),
      'delivery.' || new.status, 'campaign', new.campaign_id,
      jsonb_build_object('channel', new.channel, 'round', new.round_number, 'attempts', new.attempts,
                         'ref', left(new.result_ref, 200), 'error', left(new.last_error, 300)));
  end if;
  return null;
end; $$;
drop trigger if exists audit_deliveries on public.deliveries;
create trigger audit_deliveries after update on public.deliveries
  for each row execute function public.audit_deliveries();

create or replace function public.audit_feature_flags()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  perform public.audit(null, 'feature_flag.' || lower(tg_op), 'feature_flag', coalesce(new.key, old.key),
    case when tg_op = 'UPDATE'
      then public.audit_changes(to_jsonb(old), to_jsonb(new), array['updated_at', 'description'])
      else to_jsonb(coalesce(new, old)) - 'updated_at' end);
  return null;
end; $$;
drop trigger if exists audit_feature_flags on public.feature_flags;
create trigger audit_feature_flags after insert or update or delete on public.feature_flags
  for each row execute function public.audit_feature_flags();

-- --- Reading -----------------------------------------------------------------
-- Org managers see their organisation's trail; everyone sees their own
-- org-less events (their BYOK key changes).
alter table public.audit_log enable row level security;
create policy "audit_log_read" on public.audit_log for select to authenticated using (
  (org_id is not null and public.org_can(org_id, 'manage'))
  or (org_id is null and actor_id = auth.uid())
);
