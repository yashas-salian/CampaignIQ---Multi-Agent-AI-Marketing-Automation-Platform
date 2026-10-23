-- Persona interviews: a marketer asks one of their AI personas questions and
-- it answers in character (Edge Function persona-chat). The function writes
-- both sides with the service role; people read and clear their own chats.
-- persona_ref is 'persona:<personas.id>' for a campaign persona, or
-- 'run:<capability_runs.id>:<index>' for one from Tools → Personas.
create table if not exists public.persona_chats (
  id bigint generated always as identity primary key,
  user_id uuid not null references auth.users (id) on delete cascade,
  org_id uuid references public.organizations (id) on delete cascade,
  persona_ref text not null check (persona_ref ~ '^(persona:[0-9a-f-]{36}|run:[0-9a-f-]{36}:[0-9]+)$'),
  role text not null check (role in ('user', 'assistant')),
  content text not null check (char_length(content) between 1 and 2000),
  created_at timestamptz not null default now()
);
create index if not exists persona_chats_thread on public.persona_chats (user_id, persona_ref, created_at);

alter table public.persona_chats enable row level security;
drop policy if exists persona_chats_read_own on public.persona_chats;
create policy persona_chats_read_own on public.persona_chats for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists persona_chats_delete_own on public.persona_chats;
create policy persona_chats_delete_own on public.persona_chats for delete to authenticated using (user_id = (select auth.uid()));
revoke insert, update on public.persona_chats from anon, authenticated;
