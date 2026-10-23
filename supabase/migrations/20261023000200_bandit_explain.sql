-- "Why this ad?": the bandit's reasoning for each round's arm, recorded when it
-- picks (src/tools/bandit.py explain_choice).
alter table public.iterations add column if not exists arm_explain jsonb;

-- Security fix: bandit_arms (the learning loop's shared model) had no row-level
-- security and full grants for anon/authenticated, so anyone holding the public
-- anon key could rewrite or wipe it. Only the workers (service role) write it;
-- signed-in members may read the per-arm stats for the "learned" panel.
alter table public.bandit_arms enable row level security;
revoke insert, update, delete, truncate on public.bandit_arms from anon, authenticated;
revoke all on public.bandit_arms from anon;
drop policy if exists bandit_arms_read on public.bandit_arms;
create policy bandit_arms_read on public.bandit_arms for select to authenticated using (true);
