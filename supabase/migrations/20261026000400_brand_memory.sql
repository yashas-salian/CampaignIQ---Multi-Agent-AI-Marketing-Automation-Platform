-- Brand memory (src/capabilities/brand_memory.py, docs/BRAND_MEMORY.md).
-- Structured lessons about why the organisation decides what it decides, kept
-- apart from conversation history and the bandit's numbers. Every lesson has
-- provenance (evidence, source campaign, author), a scope (a universal brand
-- rule, or an observation that applies in a context), and a review date (and
-- optionally an expiry). Only active, unexpired lessons are ever used, and only
-- inside their own organisation. The system can propose context lessons from
-- measured results and people's reasons; it can never create a brand-wide rule.

create extension if not exists pg_trgm with schema extensions;

create table if not exists public.brand_memories (
  id uuid primary key default gen_random_uuid(),
  org_id uuid not null references public.organizations (id) on delete cascade,
  type text not null check (type in ('BRAND_PREFERENCE', 'POLICY_DECISION', 'CAMPAIGN_LESSON', 'AUDIENCE_INSIGHT', 'FAILED_EXPERIMENT')),
  lesson text not null check (char_length(trim(lesson)) between 10 and 500),
  scope text not null check (scope in ('brand', 'context')),
  -- Where a context lesson applies: {domains, channels, languages, age_brackets, income_tiers}; an absent key = any.
  conditions jsonb not null default '{}'::jsonb,
  -- Machine-checkable parts, which can only make generation stricter: {avoid_terms, prefer_terms, avoid_tones, avoid_styles}.
  directives jsonb not null default '{}'::jsonb,
  evidence jsonb not null default '[]'::jsonb,  -- [{kind, excerpt, campaign_id, round, ref, at}]
  source_campaign_id uuid references public.campaigns (id) on delete set null,
  confidence numeric not null default 0.6 check (confidence between 0 and 1),
  status text not null default 'active' check (status in ('proposed', 'active', 'rejected', 'superseded', 'expired')),
  author_kind text not null check (author_kind in ('person', 'system')),
  author_id uuid references auth.users (id) on delete set null,
  reviewed_by uuid references auth.users (id) on delete set null,
  reviewed_at timestamptz,
  review_note text,
  supersedes uuid references public.brand_memories (id) on delete set null,
  review_at timestamptz not null,             -- every lesson is looked at again by this date
  expires_at timestamptz,                     -- after this it's never used
  use_count integer not null default 0,
  last_used_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  -- One campaign, or the system, can't make a universal rule.
  constraint brand_memories_brand_rules_are_human check (scope = 'context' or author_kind = 'person'),
  constraint brand_memories_expiry_after_creation check (expires_at is null or expires_at >= created_at)
);
create index if not exists brand_memories_active on public.brand_memories (org_id, status) where status = 'active';

alter table public.brand_memories enable row level security;
drop policy if exists brand_memories_read on public.brand_memories;
create policy brand_memories_read on public.brand_memories for select to authenticated using (public.org_can(org_id, 'view'));
revoke all on public.brand_memories from anon;
revoke insert, update, delete, truncate on public.brand_memories from authenticated;
grant select on public.brand_memories to authenticated;

-- Why a Gate 2 copy edit was made (asked for when the edit changes the ad substantially).
alter table public.copy_revisions add column if not exists reason text;
alter table public.copy_revisions add column if not exists material boolean not null default false;

create or replace function public._memory_editor(p_org uuid, p_scope text)
returns void
language plpgsql stable security definer set search_path = ''
as $$
begin
  if p_scope = 'brand' and not public.org_can(p_org, 'manage') then
    raise exception 'only owners and admins can set a brand-wide rule';
  end if;
  if not (public.org_can(p_org, 'create') or public.org_can(p_org, 'manage')) then
    raise exception 'only owners, admins and marketers can change brand memory';
  end if;
end;
$$;
revoke execute on function public._memory_editor(uuid, text) from public, anon, authenticated;

-- A person records a lesson (active straight away). Brand-wide rules need an owner or admin.
create or replace function public.add_brand_lesson(
  p_org uuid, p_type text, p_lesson text, p_scope text default 'context', p_conditions jsonb default '{}'::jsonb,
  p_directives jsonb default '{}'::jsonb, p_evidence_note text default null, p_campaign uuid default null,
  p_expires_at timestamptz default null
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  mid uuid;
begin
  perform public._memory_editor(p_org, p_scope);
  if p_campaign is not null and not exists (select 1 from public.campaigns where id = p_campaign and org_id = p_org) then
    raise exception 'that campaign is not in this organisation';
  end if;
  insert into public.brand_memories (org_id, type, lesson, scope, conditions, directives, evidence, source_campaign_id, confidence,
                                     author_kind, author_id, review_at, expires_at)
  values (p_org, p_type, trim(p_lesson), p_scope, coalesce(p_conditions, '{}'::jsonb), coalesce(p_directives, '{}'::jsonb),
          case when nullif(trim(p_evidence_note), '') is null then '[]'::jsonb
               else jsonb_build_array(jsonb_build_object('kind', 'note', 'excerpt', left(trim(p_evidence_note), 400), 'at', now())) end,
          p_campaign, case when p_scope = 'brand' then 0.9 else 0.7 end, 'person', auth.uid(),
          now() + case when p_scope = 'brand' then interval '180 days' else interval '90 days' end, p_expires_at)
  returning id into mid;
  perform public.audit(p_org, 'memory.added', 'brand_memory', mid::text, jsonb_build_object('type', p_type, 'scope', p_scope));
  return mid;
end;
$$;
revoke execute on function public.add_brand_lesson(uuid, text, text, text, jsonb, jsonb, text, uuid, timestamptz) from public, anon;
grant execute on function public.add_brand_lesson(uuid, text, text, text, jsonb, jsonb, text, uuid, timestamptz) to authenticated;

-- The system proposes a context lesson from evidence; a person confirms it before it's used.
create or replace function public.propose_brand_lesson(
  p_org uuid, p_type text, p_lesson text, p_conditions jsonb, p_directives jsonb, p_evidence jsonb, p_campaign uuid, p_confidence numeric
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  mid uuid;
begin
  insert into public.brand_memories (org_id, type, lesson, scope, conditions, directives, evidence, source_campaign_id, confidence,
                                     status, author_kind, review_at, expires_at)
  values (p_org, p_type, left(trim(p_lesson), 500), 'context', coalesce(p_conditions, '{}'::jsonb), coalesce(p_directives, '{}'::jsonb),
          coalesce(p_evidence, '[]'::jsonb), p_campaign, least(greatest(coalesce(p_confidence, 0.5), 0), 1),
          'proposed', 'system', now() + interval '60 days', now() + interval '365 days')
  returning id into mid;
  perform public.audit(p_org, 'memory.proposed', 'brand_memory', mid::text, jsonb_build_object('type', p_type));
  return mid;
end;
$$;
revoke execute on function public.propose_brand_lesson(uuid, text, text, jsonb, jsonb, jsonb, uuid, numeric) from public, anon, authenticated;
grant execute on function public.propose_brand_lesson(uuid, text, text, jsonb, jsonb, jsonb, uuid, numeric) to service_role;

-- Accept or reject a proposed lesson; accepting re-confirms an active one (pushes its review date).
create or replace function public.review_brand_lesson(p_memory uuid, p_accept boolean, p_note text default null)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  m public.brand_memories;
begin
  select * into m from public.brand_memories where id = p_memory;
  if m.id is null then raise exception 'lesson not found'; end if;
  perform public._memory_editor(m.org_id, m.scope);
  if m.status not in ('proposed', 'active') then raise exception 'this lesson is no longer current'; end if;
  update public.brand_memories
     set status = case when p_accept then 'active' else 'rejected' end, reviewed_by = auth.uid(), reviewed_at = now(),
         review_note = nullif(trim(p_note), ''),
         review_at = case when p_accept then now() + case when m.scope = 'brand' then interval '180 days' else interval '90 days' end
                          else m.review_at end,
         updated_at = now()
   where id = p_memory;
  perform public.audit(m.org_id, case when p_accept then 'memory.confirmed' else 'memory.rejected' end, 'brand_memory', m.id::text,
    jsonb_build_object('note', left(coalesce(p_note, ''), 300)));
end;
$$;
revoke execute on function public.review_brand_lesson(uuid, boolean, text) from public, anon;
grant execute on function public.review_brand_lesson(uuid, boolean, text) to authenticated;

-- Correct a lesson: a new version replaces it; the old one stays as history (superseded, never used again).
create or replace function public.correct_brand_lesson(
  p_memory uuid, p_lesson text, p_scope text, p_conditions jsonb, p_directives jsonb, p_note text
)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  m public.brand_memories;
  mid uuid;
begin
  select * into m from public.brand_memories where id = p_memory;
  if m.id is null then raise exception 'lesson not found'; end if;
  -- A brand rule on either side (before or after the correction) needs an owner or admin.
  perform public._memory_editor(m.org_id, case when 'brand' in (m.scope, p_scope) then 'brand' else 'context' end);
  if m.status not in ('proposed', 'active') then raise exception 'this lesson is no longer current'; end if;
  if char_length(trim(coalesce(p_note, ''))) < 10 then raise exception 'say what was wrong with it (at least 10 characters)'; end if;
  insert into public.brand_memories (org_id, type, lesson, scope, conditions, directives, evidence, source_campaign_id, confidence,
                                     author_kind, author_id, supersedes, review_at, expires_at)
  values (m.org_id, m.type, trim(p_lesson), p_scope, coalesce(p_conditions, m.conditions), coalesce(p_directives, m.directives),
          m.evidence || jsonb_build_array(jsonb_build_object('kind', 'correction', 'excerpt', left(trim(p_note), 400), 'at', now())),
          m.source_campaign_id, greatest(m.confidence, 0.7), 'person', auth.uid(), m.id,
          now() + case when p_scope = 'brand' then interval '180 days' else interval '90 days' end, m.expires_at)
  returning id into mid;
  update public.brand_memories set status = 'superseded', updated_at = now() where id = m.id;
  perform public.audit(m.org_id, 'memory.corrected', 'brand_memory', mid::text, jsonb_build_object('supersedes', m.id, 'note', left(trim(p_note), 300)));
  return mid;
end;
$$;
revoke execute on function public.correct_brand_lesson(uuid, text, text, jsonb, jsonb, text) from public, anon;
grant execute on function public.correct_brand_lesson(uuid, text, text, jsonb, jsonb, text) to authenticated;

-- Stop using a lesson now (kept as history), or delete it outright.
create or replace function public.expire_brand_lesson(p_memory uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  m public.brand_memories;
begin
  select * into m from public.brand_memories where id = p_memory;
  if m.id is null then raise exception 'lesson not found'; end if;
  perform public._memory_editor(m.org_id, m.scope);
  update public.brand_memories set status = 'expired', expires_at = now(), updated_at = now() where id = p_memory;
  perform public.audit(m.org_id, 'memory.expired', 'brand_memory', m.id::text, '{}'::jsonb);
end;
$$;
revoke execute on function public.expire_brand_lesson(uuid) from public, anon;
grant execute on function public.expire_brand_lesson(uuid) to authenticated;

create or replace function public.delete_brand_lesson(p_memory uuid)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  m public.brand_memories;
begin
  select * into m from public.brand_memories where id = p_memory;
  if m.id is null then raise exception 'lesson not found'; end if;
  if not (public.org_can(m.org_id, 'manage') or (m.author_id = auth.uid() and public.org_can(m.org_id, 'create'))) then
    raise exception 'only owners, admins or the lesson''s author can delete it';
  end if;
  update public.brand_memories set supersedes = null where supersedes = m.id;
  delete from public.brand_memories where id = p_memory;
  perform public.audit(m.org_id, 'memory.deleted', 'brand_memory', m.id::text, jsonb_build_object('type', m.type, 'scope', m.scope));
end;
$$;
revoke execute on function public.delete_brand_lesson(uuid) from public, anon;
grant execute on function public.delete_brand_lesson(uuid) to authenticated;

-- The worker records which lessons a generation used, and retires lessons past their expiry.
create or replace function public.mark_brand_memories_used(p_ids uuid[])
returns void
language sql security definer set search_path = ''
as $$
  update public.brand_memories set use_count = use_count + 1, last_used_at = now() where id = any (p_ids) and status = 'active';
$$;
revoke execute on function public.mark_brand_memories_used(uuid[]) from public, anon, authenticated;
grant execute on function public.mark_brand_memories_used(uuid[]) to service_role;

create or replace function public.expire_brand_memories()
returns integer
language plpgsql security definer set search_path = ''
as $$
declare
  n integer;
begin
  update public.brand_memories set status = 'expired', updated_at = now()
   where status in ('active', 'proposed') and expires_at is not null and expires_at <= now();
  get diagnostics n = row_count;
  return n;
end;
$$;
revoke execute on function public.expire_brand_memories() from public, anon, authenticated;
grant execute on function public.expire_brand_memories() to service_role;

-- Gate 2 copy edits: an edit that changes the ad substantially (trigram similarity
-- below 0.5) needs a reason, which becomes a proposed lesson, or an active one
-- straight away when the editor asks for it to be remembered.
drop function if exists public.edit_round_copy(uuid, integer, text, text);
create or replace function public.edit_round_copy(
  p_campaign uuid, p_round integer, p_variant text, p_text text, p_reason text default null, p_remember boolean default false
)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  current_text text;
  gate_open boolean;
  c public.campaigns;
  is_material boolean;
  reason text := nullif(trim(coalesce(p_reason, '')), '');
begin
  if not public.campaign_can(p_campaign, 'approve') then
    raise exception 'only owners, admins and approvers can edit copy';
  end if;
  if p_variant not in ('a', 'b') then raise exception 'variant must be a or b'; end if;
  if char_length(trim(coalesce(p_text, ''))) not between 1 and 3000 then raise exception 'copy must be 1-3000 characters'; end if;
  select exists (select 1 from public.gate_decisions g where g.campaign_id = p_campaign and g.round_number = p_round
                   and g.gate_number = 2 and g.decided_at is null) into gate_open;
  if not gate_open then raise exception 'copy can only be edited while Gate 2 is open for this round'; end if;
  select * into c from public.campaigns where id = p_campaign;

  select case when p_variant = 'a' then i.copy_text else i.copy_text_b end into current_text
  from public.iterations i where i.campaign_id = p_campaign and i.round_number = p_round;
  is_material := current_text is not null and extensions.similarity(lower(current_text), lower(trim(p_text))) < 0.5;
  if is_material and char_length(coalesce(reason, '')) < 10 then
    raise exception 'this edit changes the ad substantially: say why (at least 10 characters)';
  end if;
  -- Keep the AI's original as version 1 the first time someone edits it.
  if current_text is not null and not exists (select 1 from public.copy_revisions r
       where r.campaign_id = p_campaign and r.round_number = p_round and r.variant = p_variant) then
    insert into public.copy_revisions (campaign_id, round_number, variant, copy_text, edited_by)
    values (p_campaign, p_round, p_variant, current_text, null);
  end if;
  insert into public.copy_revisions (campaign_id, round_number, variant, copy_text, edited_by, reason, material)
  values (p_campaign, p_round, p_variant, trim(p_text), auth.uid(), reason, is_material);

  if p_variant = 'a' then
    update public.iterations set copy_text = trim(p_text) where campaign_id = p_campaign and round_number = p_round;
  else
    update public.iterations set copy_text_b = trim(p_text) where campaign_id = p_campaign and round_number = p_round;
  end if;

  if reason is not null then
    insert into public.brand_memories (org_id, type, lesson, scope, conditions, evidence, source_campaign_id, confidence, status,
                                       author_kind, author_id, review_at, expires_at)
    values (c.org_id, 'BRAND_PREFERENCE', left(reason, 500), 'context',
            jsonb_build_object('domains', jsonb_build_array(c.domain_category)),
            jsonb_build_array(jsonb_build_object('kind', 'copy_edit', 'campaign_id', p_campaign, 'round', p_round,
              'before', left(coalesce(current_text, ''), 300), 'after', left(trim(p_text), 300), 'at', now())),
            p_campaign, 0.7, case when p_remember then 'active' else 'proposed' end,
            case when p_remember then 'person' else 'system' end, case when p_remember then auth.uid() end,
            now() + interval '90 days', null);
  end if;
  perform public.audit(c.org_id, 'copy.edited', 'campaign', p_campaign::text,
    jsonb_build_object('round', p_round, 'variant', p_variant, 'chars', char_length(trim(p_text)), 'material', is_material,
                       'reason', left(coalesce(reason, ''), 300)));
end;
$$;
revoke execute on function public.edit_round_copy(uuid, integer, text, text, text, boolean) from public, anon;
grant execute on function public.edit_round_copy(uuid, integer, text, text, text, boolean) to authenticated;

-- A reason given at a gate (20+ characters) is proposed as a lesson: a person
-- confirms it on the Brand memory page before it's ever used.
create or replace function public.gate_reason_to_memory()
returns trigger
language plpgsql security definer set search_path = ''
as $$
declare
  g public.gate_decisions;
  c public.campaigns;
begin
  if char_length(trim(coalesce(new.comment, ''))) < 20 then return new; end if;
  select * into g from public.gate_decisions where id = new.gate_decision_id;
  select * into c from public.campaigns where id = g.campaign_id;
  if c.org_id is null then return new; end if;
  insert into public.brand_memories (org_id, type, lesson, scope, conditions, evidence, source_campaign_id, confidence, status,
                                     author_kind, review_at, expires_at)
  values (c.org_id,
          case when new.decision = 'approve' then 'POLICY_DECISION'
               when g.gate_number = 1 then 'AUDIENCE_INSIGHT' else 'BRAND_PREFERENCE' end,
          left(trim(new.comment), 500), 'context',
          jsonb_build_object('domains', jsonb_build_array(c.domain_category)),
          jsonb_build_array(jsonb_build_object('kind', 'gate_' || new.decision, 'gate', g.gate_number, 'round', g.round_number,
                                               'campaign_id', c.id, 'excerpt', left(trim(new.comment), 300), 'at', now())),
          c.id, 0.6, 'proposed', 'system', now() + interval '60 days', now() + interval '365 days');
  return new;
end;
$$;
drop trigger if exists gate_reason_to_memory on public.gate_approvals;
create trigger gate_reason_to_memory after insert on public.gate_approvals
  for each row execute function public.gate_reason_to_memory();

-- Set by the worker when a lesson conflicts with a current policy (a claim the
-- guardrails flag or block): such a lesson is never used, and the page says why.
alter table public.brand_memories add column if not exists policy_conflict text;

create or replace function public.flag_brand_memory_conflict(p_memory uuid, p_conflict text)
returns void
language sql security definer set search_path = ''
as $$
  update public.brand_memories set policy_conflict = nullif(left(p_conflict, 300), '') where id = p_memory;
$$;
revoke execute on function public.flag_brand_memory_conflict(uuid, text) from public, anon, authenticated;
grant execute on function public.flag_brand_memory_conflict(uuid, text) to service_role;
