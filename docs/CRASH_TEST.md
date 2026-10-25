# Campaign crash test: how could this ad fail?

Before Gate 2, every ad goes through a crash test (`src/capabilities/crash_test.py`). The test covers four things:
- the post text;
- the headline on the image;
- the button;
- what the picture shows.

Gate 2 shows a **risk report**: the ad with every problem marked in place, the checks and scenarios that found each problem, and, when something is serious, a **revised version re-tested on the same scenarios**.

```
… → pre-flight → focus group → CRASH TEST → Gate 2 → posting
                                  ├─ rule checks (deterministic)
                                  ├─ simulated scenarios (marketing-risk-v1)
                                  └─ high/critical? → revise → re-test → before/after
```

## 1. Rule checks (`rules-v1`): same input, same result

| Finding | Severity | Grounded in |
|---|---|---|
| `INVENTED_TESTIMONIAL`: a named customer quote ("Rahul says…"), a rating ("4.9/5", ★★★★★) or "thousands of happy customers" the brand never provided | **critical** | The FTC Trade Regulation Rule on consumer reviews and testimonials (16 CFR 465, in force 21 Oct 2024). It bans reviews by people who don't exist, including AI-generated ones. |
| `FAKE_SOCIAL_PROOF`: "12,000 commuters already joined", "best-selling", "trusted by thousands" | high | The FTC staff report *Bringing Dark Patterns to Light* (2022) lists fake social proof as a deceptive pattern. |
| `FALSE_URGENCY`: "limited time", "only 3 left", "before the spots run out", "ends tonight" | high | The same FTC report on false urgency, scarcity and countdowns. |
| `PERSONAL_ATTRIBUTE`: "Are you struggling with debt?", "your condition" | high | Meta's advertising standards: ads can't assert or imply a viewer's health, finances or other personal attributes. |
| `UNVERIFIED_NUMBER`: a price, percentage or time that isn't in the brief | medium | Substantiation: every number in an ad needs evidence. |
| `UNSUPPORTED_CLAIM`: absolute or regulated claims ("guaranteed", "cures") | high (medium if the brand itself wrote it) | The existing claim rules in `guardrails.py` |
| `POLICY_VIOLATION`: a foreign link, a phone number, an email address, a banned word, too long for a channel. Checked on the headline and button too. | **critical** | The existing brand-safety blocks |
| `INVALID_DESTINATION` / `UNVERIFIED_DESTINATION`: the link is broken, or couldn't be checked | critical / low | The same link check as the decision engine |

**The brand's own words are never "invented".** Anything in the idea or the tagline is exempt, so if the brief says "20% off, limited time", the ad may say so too.

**Only rule checks can rate a finding critical.**

## 2. Simulated scenarios (`marketing-risk-v1`)

One LLM call plays eight people in eight situations, grounded in the campaign's personas:

| Scenario | Who | Looks for |
|---|---|---|
| `skeptic` | A customer burned by ads before | Claims they don't believe, missing proof |
| `price_sensitive` | A buyer comparing options | Unclear value, hidden costs |
| `competitor_discount` | Someone who just saw a competitor's 20% off | A reason to choose this one anyway |
| `standards_reviewer` | An advertising-standards reviewer | Unsupported, exaggerated or misleading claims |
| `three_second_scroll` | Someone who sees it for three seconds | What they think is sold, anything ambiguous |
| `sensitivity` | A viewer alert to stereotypes | Insensitive or exclusionary wording |
| `wrong_audience` | Someone outside the target audience | Confusion or annoyance that hurts the brand |
| `non_native` | A non-native reader | Idioms, slang, jargon |

**Guards on the simulation:**
- **Quotes must be real:** every finding must quote the exact ad words it's about. A quote that isn't in the ad is dropped, and the finding is then about "the ad as a whole".
- **Allowed values only:** scenarios and finding types outside the versioned lists are dropped.
- **Capped at high:** simulated findings can never be critical. Agreement between simulated people shares one model's biases, so it is **never treated as independent evidence**. The report is labelled *"Simulation, not real customers"* everywhere.

## 3. Revise, re-test, compare

**When it revises:** if anything is high or critical, one LLM call (`crashtest.revise` 1.1.0) rewrites the post, headline and button to fix the findings.

**What the revision may not do:**
- invent names, reviews, numbers, deadlines or popularity;
- add new product facts (locations, timing, fees);
- grow longer than the original.

If it comes back much longer anyway, it's asked once more for a shorter fix. This rule came from a live test, where the first prompt "fixed" an unsupported claim by adding *"based on our average timing data"*.

**The re-test:** the same rule checks and scenarios run on the revised version. The report shows which findings were **resolved**, which **remain** and which are **new**.

**At Gate 2, an approver chooses:**
- **Use the revised version** (`apply_revision` on the worker):
  - The copy goes in through the version history; the AI's original is kept as version 1.
  - A changed headline or button redraws the ad from its template and its stored painted background, with no new image generation.
- Edit by hand and **re-run the crash test**.
- Keep the original.

**The approval rule:** approving an ad whose current crash test is **critical** needs a written reason of at least 10 characters. A database trigger on `gate_approvals` enforces it. The simulator never approves anything itself.

## What's stored

**`crash_tests`:** one row per run, either the pipeline run or a re-run. Each row holds:
- the full report (original and revised findings, comparison and notes);
- the scenario set and rules version;
- the risk, and whether and by whom the revision was applied.

**Access:**
- Members of the organisation can read it. Only the worker writes it.
- Runs and applied revisions are in the audit log (`campaign.crash_test`, `campaign.crash_test_applied`).

## Where it is

- **Gate 2:** the full report, with "Use the revised version" and "Re-run the crash test".
- **Rounds list:** each round shows a "Crash test: …" chip.
- **Tools:** "Crash-test an ad". Paste any ad and get the same report, with nothing applied.
- **MCP:** the `crash_test_ad` tool.
- **API:** `GET /api/v1/campaigns/{id}/crash-tests`, and `POST` to re-run while the round waits at Gate 2. See [openapi.yaml](openapi.yaml).

## Benchmark

`python -m src.eval.crashtest_benchmark` runs the rule checks on a fixed set of ads, each with one planted problem or none. The baseline is the brand-safety checks the app had before the crash test:

<!-- benchmark:start -->
Rules `rules-v1`, 28 ads (22 with one planted problem, 6 clean) - `python -m src.eval.crashtest_benchmark`.

| | Crash-test rule checks | Brand-safety checks alone (before) |
|---|---|---|
| Planted problems caught | **22 / 22** | 6 / 22 |
| False alarms (high/critical) on clean ads | **0 / 6** | - |
| Same findings on re-run | yes | yes |

| Problem type | Caught |
|---|---|
| FAKE_SOCIAL_PROOF | 3 / 3 |
| FALSE_URGENCY | 4 / 4 |
| INVENTED_TESTIMONIAL | 4 / 4 |
| PERSONAL_ATTRIBUTE | 3 / 3 |
| POLICY_VIOLATION | 3 / 3 |
| UNSUPPORTED_CLAIM | 2 / 2 |
| UNVERIFIED_NUMBER | 3 / 3 |
<!-- benchmark:end -->

The cases and the rule wording were written together, and two rules were tightened against them. So this is a regression and consistency check, not independent proof. The simulated scenarios aren't benchmarked: they need an LLM and vary by design.

**Live check** on the real smoke-test ad ("Rahul says the moment he steps off the metro…"):
- **Rule checks:** the invented testimonial (critical) and "spots run out" (high).
- **Simulation:** "no line" overpromises at peak times; the price after the free order is unclear; a competitor's ongoing 20% beats a one-time freebie.
- **The revision:** removed the testimonial and the urgency, and softened "ready on arrival", with no new facts. Every rule finding resolved. What remained was the simulated skeptics doubting the product's core promise, which is a judgement call for the approver.

## Known limits

- **The rule patterns are English-first,** apart from numbers and links. Other languages rely more on the simulated scenarios.
- **The simulation is one model playing many people.** It's useful for spotting risks, not for predicting results.
- **A revision can't fix a problem that needs facts the brand didn't give,** such as a real price. It removes or softens the claim instead, and the remaining finding says so.
