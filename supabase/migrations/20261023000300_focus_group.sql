-- Synthetic focus group (src/capabilities/focus_group.py): the campaign's
-- personas react to each round's draft before Gate 2. Advice shown to the
-- approver; {reactions: [{name, archetype, gender, reaction, likelihood, quote}],
-- verdict: {click, scroll, object}, average_likelihood}.
alter table public.iterations add column if not exists focus_group jsonb;
