-- Bayesian A/B early stop (src/graph/nodes/metrics_collector.py): once one email
-- variant is >= 95% likely to be better, the split stops (ab_test -> false) and
-- this records the call: {winner, prob_b_beats_a, round, arm_index, image_style, copy_tone}.
alter table public.campaigns add column if not exists ab_decision jsonb;
