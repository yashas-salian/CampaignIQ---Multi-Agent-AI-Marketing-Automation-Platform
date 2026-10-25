# Proof of impact: did the campaign actually cause anything?

Clicks, likes and the email A/B test show activity. They can't show that a campaign **caused** extra sign-ups:
- people who click were often going to sign up anyway;
- a rise during the campaign may be the season, not the ad.

The proof-of-impact engine (`src/capabilities/impact.py`) runs a campaign's email audience as a **pre-registered randomized experiment**:
- a randomly chosen **control group gets nothing**;
- the difference in outcomes between the groups is the campaign's effect.

```
declare (before the first send) ──▶ first send: stable random assignment ──▶ control: never emailed
                                                                         └─▶ treatment: one email each, own link token
links ─▶ track-click (click credited to the person) ─▶ brand's site ─▶ POST /v1/conversions (token or email)
hourly: analyse ──▶ COLLECTING (interim, no verdict) ──▶ at the predeclared end: verdict ──▶ bandit learns
```

## 1. The design is declared first, then locked

On the campaign page (**Proof of impact → Set up the experiment**), before the first email, someone with the create or manage right declares:

| Field | Meaning |
|---|---|
| Hypothesis | What the campaign is expected to do |
| Primary metric | `qualified_signup_rate` (default), `conversion_rate`, or `click_through_rate`. Click-through is allowed only for A vs B: a control group never gets a link, so it can't click. The database enforces this. |
| Control group | 10–50% of recipients get nothing. With the A/B test on, "none" compares B with A (no control group). |
| Sending period, attribution window | The stopping rule is a **fixed horizon**: the final analysis happens at *period + window*, or *finish + window* if the campaign ends early. |
| Smallest lift worth acting on | The bar for "no meaningful impact" |
| Expected baseline | Used only for planning. The form shows the sample needed per group (two-sided 5%, 80% power) next to the group sizes the list allows, and warns when they're too small. |

**When it locks:** the first send starts the experiment, and from then on a database trigger refuses any change to the design, even from a worker. Before that, the experiment can be edited or withdrawn.

**Everything is audited:** declaring, starting and concluding are audit-logged, and so reach webhooks.

## 2. Assignment

**Unit:** one email recipient.

**How a person is assigned:**
1. `unit = sha256(experiment id : normalised address)`. The address itself isn't stored with the assignment.
2. The arm comes from a second hash, compared with the declared shares.
3. The assignment is stored on first use. Each later send:
   - re-reads the stored assignments, page by page (an API response stops at 1000 rows);
   - adds only addresses that are new;
   - never moves anyone.

Retries, resumed runs and later rounds therefore keep everyone in the same group. A test proves that even a caller proposing a different arm changes nothing.

**What each group receives:**
- **Control:** never emailed.
- **Treatment:** one email per person, each with its own idempotency key, so a retry after a partial failure never emails anyone twice. Each link carries the person's token; that also means nobody sees the other addresses.
- **With the A/B test on:** treatment is split into A and B by the same stable hash.

The Bayesian early stop of the A/B test is switched off while an experiment runs. Stopping on a peek would break a fixed-horizon design.

## 3. Outcomes are events with a source and a time

| Event | Source | How it's matched |
|---|---|---|
| `exposure` | the send (`email_send`) | recorded per person and round, after the email went out |
| `click` | `track-click` | the link's token (`t`). The redirect passes it on as `ciq_t`. |
| `conversion` | `POST /v1/conversions` from the brand's site | the `ciq_t` token, or the person's email address, hashed with the experiment id |

**Matching by address** is the only way a control person can be matched, since they never got a link.

**Conversion events:**
- carry `qualified`, an optional `value` and `currency`, and the brand's `event_id`;
- a retried postback with the same `event_id` counts once;
- conversions that match nobody are kept apart and reported, never counted.

**Who can read what:** members can read the experiment and its stored result. Assignments (tokens) and raw events are for the workers only (RLS).

## 4. The analysis (`impact-v1`, deterministic)

The analysis is **intention-to-treat**: everyone counts in the group they were assigned to, whether or not the email arrived. A person succeeds if their primary metric happened between the first send and the end of the attribution window.

| Number | Method |
|---|---|
| Rate per group | successes / people, with a **Wilson** 95% interval |
| Absolute lift | treatment − control, with a **Newcombe hybrid-score** 95% interval (Newcombe 1998, method 10). It stays well-behaved with zero conversions, small samples and unequal groups; the unit test reproduces the paper's worked example. |
| Chance the campaign helped | P(treatment > control) from Beta(1, 1) posteriors (fixed seed: reproducible) |
| Relative lift | posterior median and 95% interval, **only when the control group has ≥ 10 successes**. Otherwise it isn't shown: dividing by a handful of events gives meaningless percentages. |
| Extra successes caused | lift × treatment size, with the interval scaled the same way |
| Extra revenue caused | extra conversions (same Newcombe interval) × the average conversion value. This assumes the campaign changes how many people buy, not how much each spends. |
| Revenue after a click | purchases within the window after a click: **attribution, not causal**, shown apart |
| Sample-ratio check | chi-square of the group sizes against the declared split. p < 0.001 means the assignment (or the data pipeline) broke. |

**Kept apart everywhere:**
- **observed counts:** per group, emailed, clicked, converted;
- **the causal estimate:** from the randomized comparison only;
- **attribution-based revenue.**

Nothing compares before with after.

### Verdicts

Before the predeclared end the status is **`COLLECTING`**. Interim numbers are shown and labelled, but there's no verdict: nobody stops early on a lucky peek. At the end, the first matching rule wins:

| Order | Condition | Status |
|---|---|---|
| 1 | sample-ratio mismatch | `INCONCLUSIVE` / `SAMPLE_RATIO_MISMATCH` |
| 2 | conversion metric and no conversions reported for anyone | `INCONCLUSIVE` / `NO_OUTCOME_DATA` (silence isn't "no effect") |
| 3 | a group below the declared minimum | `INCONCLUSIVE` / `INSUFFICIENT_DATA` |
| 4 | interval entirely above 0 | `POSITIVE_IMPACT` |
| 5 | interval entirely below 0 | `NEGATIVE_IMPACT` |
| 6 | interval within ± the smallest worthwhile lift | `NO_MEANINGFUL_IMPACT` |
| 7 | otherwise | `INCONCLUSIVE` / `INTERVAL_TOO_WIDE` |

**Freshness checks:**
- **While running:** the report flags a conversion source that went quiet for 3 days, and no conversions at all after 3 days.
- **Always shown:** when it was last analysed (hourly, in the campaign-loop sweep: `python -m src.capabilities.impact`).

**Stored result:** the final result is written once (`save_impact`) and audited as `experiment.concluded`. A later save never overwrites it.

### Assumptions shown with every report

- **Intention to treat:** everyone counts in the group they were assigned to.
- **Fixed outcome window:** only conversions inside the window count.
- **The control group still sees social posts:** the estimate is what the *email* adds on top.
- **Matching by token or address:** someone who signs up with another address isn't matched, in either group. That dilutes the estimate equally and doesn't bias it.

## 5. The bandit learns from a valid result, once

When the final result isn't broken (no sample-ratio mismatch, and outcome data exists), the bandit gets an explicitly defined reward:
- **Reward:** the primary metric, credited to the latest email a treatment person received before their success.
- **Granularity:** per round and email variant.
- **Context:** the experiment's real context (the email channel, the campaign's primary persona and domain).

**Fed once:** `bandit_fed_at` makes sure it happens only once. The control group's conversions teach it nothing, because no creative was shown.

## 6. API

**`GET /v1/experiments/{id}/impact`** (the spec's suggested shape):

```json
{
  "status": "INCONCLUSIVE",
  "primaryMetric": "qualified_signup_rate",
  "controlRate": null,
  "treatmentRate": null,
  "absoluteLift": null,
  "confidenceOrCredibleInterval": null,
  "reason": "INSUFFICIENT_DATA"
}
```

It also includes:
- `intervalMethod` (`newcombe_hybrid_score_95`);
- `probabilityTreatmentBetter`;
- `relativeLift`;
- `final`;
- `analyzedAt`.

**Other routes:**
- **`GET /v1/campaigns/{id}/experiment`:** the declared design and the full latest result.
- **`POST /v1/conversions`** (write scope):

  ```json
  { "experiment_id": "…", "event_id": "order-123", "token": "<ciq_t>", "qualified": true, "value": 25, "currency": "USD" }
  ```

  Instead of `token`, send `email`; instead of `experiment_id`, send `campaign_id`. It answers `202 { matched, duplicate, counted }`.
- **MCP tool `measure_impact`:** the same analysis on aggregated counts from any randomized holdout.

## 7. Benchmark: known truths before real use

`python -m src.eval.impact_benchmark` draws hundreds of synthetic experiments per scenario, each with a known true effect, and runs every one through the engine's final analysis. Two shortcuts run on the same draws for comparison:
- **"Point estimate":** the campaign worked if its group's rate is higher.
- **"Before/after":** the campaign worked if the rate during it beats the rate before it.

**What counts as a false claim:** saying there's an effect when there isn't one, or getting the sign wrong.

<!-- benchmark:start -->
Policy `impact-v1`, 400 simulated experiments per scenario (seed 20261026).

| Scenario | Truth | Engine right | Engine false claims | Point estimate false claims | Before/after false claims | Engine's usual reason |
|---|---|---|---|---|---|---|
| No effect, 20/80 split | none | 93% | 7% | 99% | 98% | `INTERVAL_TOO_WIDE` |
| Real lift, 3% to 5% | positive | 96% | 0% | 0% | 0% | `INTERVAL_ABOVE_ZERO` |
| Real harm, 5% to 3% | negative | 98% | 0% | 0% | 0% | `INTERVAL_BELOW_ZERO` |
| Lift below the 1-point bar, big sample | none | 100% | 0% | 100% | 99% | `INTERVAL_WITHIN_MIN_EFFECT` |
| Real lift, only 30 held out | positive | 100% | 0% | 18% | 8% | `INSUFFICIENT_DATA` |
| No effect, 5/95 split | none | 96% | 4% | 100% | 98% | `INTERVAL_TOO_WIDE` |
| No conversions reported at all | none | 100% | 0% | 0% | 0% | `NO_OUTCOME_DATA` |
| Assignment broke: 15% held out, 20% declared | none | 100% | 0% | 100% | 99% | `SAMPLE_RATIO_MISMATCH` |
| Market rose 2% to 3% for everyone, campaign did nothing | none | 96% | 4% | 99% | 100% | `INTERVAL_TOO_WIDE` |

Across the three no-effect scenarios with usable data the engine claimed an effect in 5.2% of experiments; the point estimate did in 99% and before/after in 99%.
<!-- benchmark:end -->

**How to read it:**
- **No-effect scenarios:** the engine's false-claim rate stays near the 5% a 95% interval allows.
- **Real effects:** it finds them, and it says "inconclusive" when 30 people were held out.
- **Broken split or no conversion data:** it never reports an effect.
- **The shortcuts:** they claim an effect almost every time there is none, including the seasonal case, where the whole market rose and the campaign did nothing.

## 8. Tests

| Suite | What it proves |
|---|---|
| `tests/unit/test_impact.py` (27) | **Assignment:** stable and normalised; split matches the shares. **Statistics:** Newcombe against the published example; zero conversions, small samples, unequal groups; sample-ratio check; sample size. **Verdicts:** every verdict and reason; no verdict before the end; relative lift only with a supported baseline; the outcome window; unmatched and unqualified conversions; causal vs attributed revenue; stale sources; A vs B and holdout + A/B. **Integration points:** the API view; the bandit reward and its refusal on a broken experiment; one email per person with their own link and key; exposures recorded on a partial failure; the control never emailed; the early A/B stop waiting; the benchmark's bar. |
| `tests/integration/test_db_experiments.py` (9) | **Declaring:** rights; metric fits the design; needs an audience; locked after the start (even for workers); refused once emails went out. **Data:** assignments never move; conversions matched by token or hashed address and counted once; final result written once; an early finish brings the analysis forward. **Access:** RLS, and withdrawing. |
| `frontend/e2e/impact.spec.ts` (7 × desktop and phone) | **Setup:** pre-registering with the sample-size plan; the declared design and withdrawing. **Report:** causal, observed and attribution apart; interim without a verdict; no conversions is inconclusive. **Access and layout:** viewers see no setup; no sideways scroll at 320 px. |

**End-to-end local run** (no emails sent): 2,000 recipients assigned 1,594 / 406 (sample-ratio p = 0.74); conversions posted by token (treatment) and by hashed address (control), with the true lift set to +5 points. The final analysis gave **+4.4 points (95%: +1.7 to +6.6) → `POSITIVE_IMPACT`**, stored once, with the bandit fed once.
