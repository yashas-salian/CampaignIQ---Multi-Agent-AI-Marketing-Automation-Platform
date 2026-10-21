-- Brand-safety results for each round's creative (src/capabilities/guardrails.py):
-- {"issues": [{"code", "severity": "block"|"review", "message"}], "disclaimer"}.
-- Shown at Gate 2 so the approver sees claims to substantiate and anything
-- that will stop the send.
alter table public.iterations add column if not exists guardrail_flags jsonb;
