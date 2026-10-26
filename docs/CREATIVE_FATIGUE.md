# Creative fatigue: is an ad concept wearing out?

The novelty check stops near-duplicate ads before they're made. Fatigue is a different question.

**Fatigue** is when a concept the same people keep seeing loses effect round after round. An original ad can wear out, and a repeated one can keep working. So fatigue is judged from **results**, and near-duplicates are reported **separately**.

The **Creative fatigue** panel on the campaign page (`src/capabilities/fatigue.py`, policy `fatigue-v1`) runs after every round's metrics:

```
round metrics ──▶ rate per round (real denominators) ──▶ the rule ──▶ verdict per channel and segment
                                                                     │  FATIGUE_SUSPECTED / CONFIRMED
                                                                     ▼
                         alert + proposed refresh (change the repeated feature) ──▶ people: change it or keep the ad
                                                                     ▼
                         next round's creative (guardrails, pre-flight, crash test, Gate 2 as usual)
                                                                     ▼
                         its results vs the fatigued rounds ──▶ IMPROVED / NO_CHANGE / WORSE / INCONCLUSIVE ──▶ learning
```

## 1. What's measured

**Unit:** a channel and audience segment. For email, variants A and B are separate segments, since each reaches its own half of the list. Each segment's rounds are its exposure periods.

**Email has a real denominator.**
- **People tracked:** when the proof-of-impact experiment tracks people, the rate is unique clickers over the people emailed that round (F-03's per-person events).
- **Otherwise:** clicks over recipients, capped at one per recipient and marked as not unique.
- **Missing results:** a round whose metrics never arrived is marked *no results* and doesn't count.

**Social channels report no impressions.** Bluesky, Mastodon and Reddit give likes, reposts and replies, but not how many people saw the post. Their engagement trend is shown, but the verdict is always **NOT_MEASURABLE**: falling likes are never called fatigue.

## 2. The rule (`fatigue-v1`)

The rule decides from the rates; the similarity between creatives only decides whether a drop is the creative's fault.

**1. Enough data.** At least 3 rounds that each reached 100+ people and have results. Otherwise **INSUFFICIENT_DATA**.

**2. Baseline and recent rounds.**
- The **baseline** is the concept's first rounds, when it was fresh: rounds 1–2 if there are 4 or more rounds, else round 1.
- The **recent** rounds are the last two.

**3. Sustained.** Every recent round, on its own, must be:
- at least 10% below the fresh baseline, and
- below it beyond its own noise: the round's 80% one-sided interval, Newcombe, is clear of the baseline.

One bad round followed by an ordinary one isn't a trend.

**4. Large enough.** A relative drop of at least 20%. Otherwise **NO_FATIGUE**.

**5. Specific to the creative.**
- **The market or the audience:** if the other email variant, or the organisation's other emails over the same windows, dropped nearly as much (within 15 points), the verdict is **NOT_ATTRIBUTABLE** (`MARKET_OR_AUDIENCE_DROP`).
- **Different ads:** if the recent creatives aren't the same concept as the fresh ones (combined similarity below 0.70), repetition can't be the cause. The verdict is again **NOT_ATTRIBUTABLE** (`CREATIVES_DIFFER`).

**6. Clear.**

| Condition | Verdict | Recommendation |
|---|---|---|
| The whole 95% interval of the drop is below zero | **FATIGUE_CONFIRMED** | **RETIRE** if the creatives are near-identical (≥ 0.85), else **TEST_REFRESH** |
| Clear only at 80% | **FATIGUE_SUSPECTED** | **TEST_REFRESH**, a cheap test |
| Neither | **NO_FATIGUE** | **KEEP** (within noise) |

**Similarity** compares each recent creative with each fresh one, using five features:

| Feature | Weight | How it's measured |
|---|---|---|
| Wording | 0.35 | meaning, from the multilingual embeddings the novelty check uses |
| Visual | 0.25 | same layout template = 1; same image style = 0.6 |
| Opening line | 0.2 | word overlap of the first sentence |
| Offer | 0.1 | only when either ad has one |
| Button text | 0.1 | exact match |

**Near-duplicates** (combined ≥ 0.85, the novelty check's threshold) are listed in their own section, whatever the results.

## 3. Refreshes

**The proposal.** A new FATIGUE_SUSPECTED or FATIGUE_CONFIRMED alert comes with a proposed refresh for the next round, aimed at the feature that repeats most:

| Strategy | What changes |
|---|---|
| `NEW_HOOK` | a clearly different first sentence than the ones the audience has seen, with the same facts |
| `NEW_VISUAL` | a different image style (the best-ranked bandit arm that changes it) and layout |
| `NEW_ANGLE` | a different tone (an arm that changes it) and angle |
| `NEW_OFFER_FRAMING` | lead with a different benefit, and **never invent offers, prices or deadlines** |

**What experience changes.** Past outcomes for the same organisation, channel and industry can override the proposal. A strategy needs 2+ tries and a Beta(1, 1) posterior mean of "improved" above 0.5.

**The people's choice.** Owners, admins and marketers can pick another strategy, or **keep the creative** with a note, which closes the alert and cancels the refresh. Only one refresh waits per campaign; the database enforces this.

**Where it applies.** The refresh reaches the next round as revision guidance and, for visual or angle, a different arm. The new creative still passes the guardrails, pre-flight, crash test and **Gate 2 approval**. Competitor text never enters (see the competitor feature).

**Measured, not assumed.**
- **The comparison:** when the refreshed round has results, its rate is compared with the two fatigued rounds before it, using Newcombe's 95% interval on the change.
- **Outcomes:**
  - **IMPROVED** only when the whole interval is above zero;
  - **WORSE** when it's all below;
  - **NO_CHANGE** when it's all within ±20% of the earlier rate;
  - otherwise **INCONCLUSIVE**, which is also the outcome if either side reached fewer than 100 people.
- **The caveat:** this is a sequential before/after comparison on the same audience, and the panel says so. It isn't randomized. When the campaign runs an A/B test, the other variant over the same rounds is the comparison the rule already uses for specificity.
- **Learning:** outcomes are stored per organisation, channel and industry, and steer the next proposal (section above).

## 4. API and tools

- **`GET /v1/campaigns/{id}/creative-fatigue`** (read scope) returns:
  - `segments`: verdict, reason, recommendation, per-round periods, baseline and recent rates with intervals, drop and its interval, similarity, comparator drops, the suggested strategy and its record;
  - `duplicates`;
  - `alerts`;
  - `refreshes`: each with its strategy, round, outcome and detail, and whether the system or a person proposed it.
- **MCP tool `assess_creative_fatigue`:** the same rule on round-by-round counts you supply.

## 5. Benchmark (`python -m src.eval.fatigue_benchmark`)

Synthetic campaigns where the truth is known, 5 rounds each, compared with a naive rule: "the latest round did worse than the one before".

<!-- benchmark:start -->
Policy `fatigue-v1`, 400 simulated campaigns per scenario, 5 rounds each (seed 20261027).

| Scenario | Creative fatigue? | Engine alerts | Naive rule alerts | Engine's usual verdict |
|---|---|---|---|---|
| Steady concept, no change | no | 6% | 43% | `NO_FATIGUE` |
| Same concept wearing out (-50% by round 5) | yes | 80% | 67% | `FATIGUE_CONFIRMED` |
| Similar but not identical concept wearing out | yes | 82% | 64% | `FATIGUE_CONFIRMED` |
| One bad round, then back to normal | no | 17% | 8% | `NO_FATIGUE` |
| Everyone's emails dropped 45% (the market) | no | 13% | 51% | `NOT_ATTRIBUTABLE` |
| Decline, but every round's ad was different | no | 0% | 66% | `NOT_ATTRIBUTABLE` |
| A 10% dip, within normal variation | no | 12% | 44% | `NO_FATIGUE` |
| Wearing out, but only 60 people per round | yes | 0% | 44% | `INSUFFICIENT_DATA` |
| A social channel: likes falling, no impressions | yes | 0% | 65% | `NOT_MEASURABLE` |

Across the scenarios without creative fatigue the engine alerted in 9.8% of campaigns, the naive rule in 42%. With enough people per round it caught 80% of worn-out concepts; on 60-person lists and on social channels it says the data can't tell, by design.
<!-- benchmark:end -->

**How to read it:**
- **Precision:** the engine alerts far less often when there's no creative fatigue.
- **Detection:** it catches most worn-out concepts that reached enough people.
- **When it can't tell:** with 60-person lists or no reach data, it says so instead of guessing.

**Its weak spot is a bad round second-to-last.** That round sits inside the "recent" window, and an ordinary last round that happens to land low completes a false trend (17% of such campaigns). The naive rule does better there (8%), because the last round looks like a recovery. Raising the per-round bar would cut this case, but it would also miss more real fatigue. The rule was tuned on these scenarios, so treat the table as a regression check, not proof on real campaigns.

## 6. Tests

| Suite | What it proves |
|---|---|
| `tests/unit/test_fatigue.py` (16) | **The rule:** every verdict and reason (confirmed/retire, suspected, insufficient and stale, no denominator, one bad round, small dips, market drop, different creatives). **Similarity:** per variant; an offer neither ad has is ignored; duplicates are apart from fatigue. **Refreshes:** the strategy (most repeated feature, overridden only by proven experience); directives that never invite new claims; the arm change; the four outcomes. **Integration:** the refresh reaching the next round; email denominators without tracking; the benchmark's bar. |
| `tests/integration/test_db_fatigue.py` (4) | who can refresh or keep; one waiting refresh per campaign and a new pick replaces it; keeping cancels the refresh and closes the alert (audited); members read, nobody writes directly |
| `frontend/e2e/fatigue.spec.ts` (7 × desktop and phone) | the verdict with its evidence; social shown but not judged; changing the refresh or keeping the creative; refreshes with outcomes and duplicates apart; viewers read only; no sideways scroll at 320 px |

**Live local run** (real embeddings, the local database):
- **Setup:** 5 rounds of 800 emails with near-identical coffee ads falling from 6.2% to 3.0%.
- **Verdict:** **FATIGUE_CONFIRMED** (−47%, 95% interval −4.4 to −1.4 points), with similarity 0.88, so **RETIRE**. Rounds 2–5 were also listed as near-duplicates of round 1.
- **Refresh:** the system proposed `NEW_VISUAL` (the visual was identical). Round 6 got the guidance and a different image style.
- **Outcome:** round 6 landed at 5.5%, giving **IMPROVED** (+2.3 points, interval +0.6 to +4.2), and the alert closed.
