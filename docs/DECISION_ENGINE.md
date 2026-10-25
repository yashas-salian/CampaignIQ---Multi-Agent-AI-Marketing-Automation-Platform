# Decision intelligence: knowing when *not* to advertise

A feasible idea isn't automatically a good investment:
- a topic can be popular without anyone wanting to buy;
- a market can be crowded;
- the audience can be on channels we don't post to.

Before any creative is made, the decision engine (`src/capabilities/decision.py`) reads the evidence gathered so far and recommends one of five outcomes:

| Outcome | Meaning | What happens |
|---|---|---|
| **LAUNCH** | A strong, well-evidenced opportunity with no red flags | Gate 1 as usual |
| **TEST_SMALL** | Worth trying, but uncertain or with a weakness | Gate 1. The campaign is capped at **2 rounds**. |
| **WAIT** | Demand is low now but clearly rising | Gate 1. The daily market watch **re-evaluates** once search interest reaches the stated threshold, and notifies the approvers. |
| **KILL** | Weak opportunity (*soft*) or a hard block | Soft: Gate 1, where approving needs a written reason. Hard block: the campaign stops as **blocked** and can never be approved. |
| **INSUFFICIENT_EVIDENCE** | Too little or too stale evidence | Gate 1, where approving needs a written reason. No score is shown. |

A person always decides at Gate 1. The engine only recommends. The exception is a hard block, which no score and no approver can override; the database enforces this.

## Where it runs

```
idea → feasibility research → personas → DECIDE → Gate 1 → creative → …
                                            └─ hard block → status "blocked" (end)
```

- **Graph node:** `src/graph/nodes/decision.py`. If the engine itself fails, the campaign continues to Gate 1 without a recommendation rather than stopping.
- **Tools page:** "Should we advertise?" runs the same research, personas and decision without starting a campaign.
- **MCP:** the `evaluate_decision` tool.
- **API:** see [the endpoints below](#api).

## How it decides

**Deterministic, with no LLM call.** The same evidence and policy version always give the same decision (`evaluate()` is pure), so every recommendation can be reproduced and audited.

### 1. Hard constraints first

These block whatever the score:

| Code | What |
|---|---|
| `PROHIBITED_PRODUCT` | Products Meta and Google don't allow advertising: illegal drugs, weapons and ammunition (not water guns or glue guns), counterfeits, fake documents, spyware, adult content |
| `UNSUPPORTABLE_CLAIM` | Claims no evidence could support: "cures diabetes", "guaranteed returns", "double your money", "lose 10 kg in 7 days" |
| `BANNED_TERM` | The default banned list plus the brand kit's forbidden words |
| `INVALID_DESTINATION` | The CTA link is not a web address, its host doesn't exist, or it returns 404/410 |

A timeout or a 5xx answer is not a block. It's flagged `DESTINATION_UNVERIFIED` instead.

Softer claims ("clinically proven", "#1") don't block. They're raised as `CLAIM_NEEDS_EVIDENCE` review flags.

### 2. A six-factor scorecard

The list is kept short on purpose: long scorecards pull every score to the middle.

| Factor | Weight | Evidence | Reliability |
|---|---|---|---|
| Demand | 25% | Google Trends: latest and average interest | measured |
| Momentum | 10% | Google Trends: latest vs average | measured |
| Purchase intent | 20% | Share of news headlines and Bluesky/Mastodon posts using buying words ("buy", "order", "discount") or comparing words ("best", "review", "vs", "price"). Word lists exist for en, es, fr, pt and hi. Needs at least 5 texts. | proxy |
| Competition | 15% | News coverage volume (log scale) as a stand-in for saturation. No ad-spend data is available. | proxy |
| Audience reach | 15% | Share of personas whose channels match the ones we post to | estimate (simulated personas) |
| Track record | 15% | This organisation's mean reward in the category. Needs 2 or more measured campaigns. | measured |

Each factor records its **source**, **when it was fetched** and its **reliability**.

**Missing or stale evidence never counts as zero.** "Stale" means more than 72 hours old.
- The factor is left out of the score.
- Its weight is added to the **uncertainty** (the share of the scorecard without evidence).
- It gets a reason code (`MISSING_DEMAND_DATA`, `STALE_EVIDENCE`, …).

The opportunity score is the weighted mean of the factors that have evidence. It is hidden when the uncertainty is above 50%.

### 3. The policy (`decision-v1`)

1. Any hard block → **KILL** (blocked).
2. Uncertainty > 0.5, or neither demand nor intent measured → **INSUFFICIENT_EVIDENCE**.
3. Strong momentum (≥ 0.75), weak demand (< 0.35) and score < 55 → **WAIT**. The re-check threshold is max(30, 1.5 × the average interest).
4. **LAUNCH** needs all of:
   - score ≥ 65;
   - uncertainty ≤ 0.35;
   - demand was measured;
   - no red flag (≤ 0.35) on demand, purchase intent or competition.
5. Score ≥ 40 → **TEST_SMALL**.
6. Otherwise → **KILL** (soft).

Reason codes summarise why:
- strong (≥ 0.65) or weak (≤ 0.35) factors;
- gaps in the evidence;
- hard blocks.

## What's stored

**`campaign_decisions`** holds one row per decision. A re-evaluation adds a row with `trigger = 'reevaluation'`. Each row stores:
- the decision, score, uncertainty and reason codes;
- every factor, plus any hard blocks, review flags, constraints and re-check trigger;
- the **baseline** (what "launch whenever feasibility ≥ 40" would have said);
- the policy version;
- a **snapshot of the inputs**, so the decision can be reproduced later;
- the **outcome**: the campaign's rounds and mean/best reward, written back when it finishes.

**Access:**
- Members of the organisation can read the rows. Only the worker writes them.
- Every decision is in the audit log (`campaign.decision`).
- Approving at Gate 1 against KILL, WAIT or INSUFFICIENT_EVIDENCE needs a reason of at least 10 characters, enforced by a trigger on `gate_approvals`. A hard block can't be approved at all.

## API

| Endpoint | Scope | |
|---|---|---|
| `GET /api/v1/campaigns/{id}/decision` | read | `latest` plus `history` (re-evaluations) |
| `POST /api/v1/decision-engine/evaluate` | write | `{ idea, target_language?, cta_url? }` → `202 { evaluation_id, poll }`. Counts as a Tools run. |
| `GET /api/v1/decision-engine/evaluations/{id}` | read | Status and result once completed |

The schemas are in [openapi.yaml](openapi.yaml).

## Benchmark

`python -m src.eval.decision_benchmark` runs a fixed suite of hand-labelled campaign situations (`src/eval/decision_scenarios.py`). It compares the engine with the rule it replaces, "launch whenever feasibility ≥ 40":

<!-- benchmark:start -->
Policy `decision-v1`, 25 scenarios (`python -m src.eval.decision_benchmark`).

| | Decision engine | Baseline: launch if feasibility ≥ 40 |
|---|---|---|
| Matches the expected decision | **96%** | 28% |
| Launches a hard-blocked campaign (of 6) | **0** | 4 |
| Spends on a weak opportunity (of 5) | **0** | 2 |
| Same output on re-run | yes | yes |

| Scenario | Expected | Engine | Baseline | Score | Why (expected) |
|---|---|---|---|---|---|
| strong_everything | LAUNCH | LAUNCH | LAUNCH | 83 | High, rising demand; people talk about buying; reachable; it has worked before. |
| strong_no_history | LAUNCH | LAUNCH | LAUNCH | 84 | Strong market signals; no history yet is a gap, not a red flag. |
| trending_no_buyers | TEST_SMALL | TEST_SMALL | LAUNCH | 47 | Everyone talks about it, nobody wants to buy, and coverage is crowded: test, don't commit. |
| niche_with_buyers | TEST_SMALL | TEST_SMALL | KILL | 66 | Tiny search demand but the few who talk about it want to buy, and no competitors: a small test. |
| dead_market | KILL | KILL | KILL | 26 | No demand, falling, nobody buying, hard to reach. |
| rising_early_weak | WAIT | WAIT | KILL | 48 | Interest has tripled but is still low and nobody is buying yet: re-check when it peaks. |
| rising_with_buyers | TEST_SMALL | TEST_SMALL | KILL | 68 | Fast-rising topic with real buying talk: get in early, but small. |
| prohibited_weapons | KILL | KILL | LAUNCH | 82 | Ad platforms don't allow advertising firearms, whatever the demand. |
| counterfeit | KILL | KILL | KILL | 83 | Counterfeit goods: prohibited. |
| miracle_cure | KILL | KILL | LAUNCH | 80 | An unsubstantiable medical claim in the product itself. |
| guaranteed_returns | KILL | KILL | LAUNCH | 82 | Promising guaranteed investment returns is illegal advertising. |
| broken_link | KILL | KILL | LAUNCH | 84 | Great opportunity, but the call-to-action link doesn't exist: fix it first. |
| banned_word | KILL | KILL | KILL | 83 | Uses a word the brand has banned. |
| no_signals | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | KILL | — | Trends and news both failed and there's barely any conversation. |
| stale_signals | INSUFFICIENT_EVIDENCE | INSUFFICIENT_EVIDENCE | LAUNCH | — | Everything was measured five days ago: refresh before deciding. |
| demand_missing_rest_good | TEST_SMALL | TEST_SMALL | KILL | 83 | Search data unavailable; buying talk and history are good: test rather than launch blind. |
| saturated_big_demand | TEST_SMALL | TEST_SMALL | LAUNCH | 69 | Huge demand and buyers, but the space is crowded: test a differentiated angle first. |
| unreachable_audience | TEST_SMALL | TEST_SMALL | KILL | 61 | Good market, but the audience lives on channels we don't post to. |
| proven_category | LAUNCH | LAUNCH | KILL | 70 | Moderate market, and this organisation's campaigns in the category do well. |
| poor_track_record | TEST_SMALL | TEST_SMALL | KILL | 56 | Same moderate market, but past campaigns in the category flopped. |
| falling_market | KILL | KILL | LAUNCH | 35 | Interest has collapsed to a quarter of its average and buying talk is thin. |
| few_posts | TEST_SMALL | TEST_SMALL | KILL | 60 | Decent demand but too few posts to judge buying intent: test. |
| claim_needs_review | LAUNCH | LAUNCH | LAUNCH | 83 | Strong market; 'clinically proven' isn't a block, but needs evidence before it's in an ad. |
| link_unverified | LAUNCH | LAUNCH | LAUNCH | 84 | Strong market; the link timed out once, which is flagged but doesn't block. |
| hindi_market | TEST_SMALL | LAUNCH ✗ | KILL | 72 | Hindi-language market with buying talk, moderate demand and no history. |
<!-- benchmark:end -->

**What this does and doesn't show:**
- **The labels are hand-written judgements, and the thresholds were set alongside them.** Agreement is a consistency check, not independent proof.
- **The disagreement is kept in the suite on purpose.** The engine says LAUNCH for a moderate-demand Hindi market with strong buying talk; the label says test small first.
- **Real validation comes from the stored outcomes.** Each campaign's eventual rewards sit next to the recommendation in `campaign_decisions`.
- **The safety numbers are structural.** No score can launch a hard-blocked idea, and the baseline launches 4 of the 6.

## Known limits

- **Purchase intent and competition are proxies:** keyword matching, and news volume rather than ad-spend data. The card labels them "proxy".
- **Audience reach comes from simulated personas** (labelled "estimate"), not observed customers.
- **The prohibited-product and claim lists are deliberately short.** They catch the clear cases. Platform ad review still applies.
- **Purchase-intent word lists cover the five campaign languages,** and only the most common words in each.
