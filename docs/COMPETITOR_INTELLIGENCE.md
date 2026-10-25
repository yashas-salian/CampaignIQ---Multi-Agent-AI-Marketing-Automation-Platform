# Competitor intelligence: what are competitors doing, and should we respond?

Market moments tell you a topic got hot. They don't tell you that a competitor just cut its price, launched a product or changed its pitch.

**Competitors** (sidebar → Insights → Competitors; `src/capabilities/competitors.py`) watches the competitors an organisation names, through public sources a person approved. It turns what changed into timestamped, sourced events and recommends a response, keeping three things apart:
- **what was observed:** the move, quoted, with its source and time;
- **what it might mean:** inferred intent, labelled as hypotheses;
- **what's forecast:** a measurable prediction checked against reality.

```
approved sources ──▶ fetch (robots.txt, identified, rate-limited) ──▶ what changed ──▶ events (observed)
                                                                                │  one story, however many outlets
                                                                                ▼
                         insight (competitor-v1): RESPOND · MONITOR · DIFFERENTIATE · NO_ACTION, all four weighed
                         inferred intent (LLM, labelled hypotheses + alternatives)
                         forecast (trend-v1): search interest over 2 weeks, 80% range ──▶ checked when due
                                                                                │
                                                     decision engine: a COMPETITOR_MOVE review flag (never the score)
```

## 1. Sources: permitted, public, approved

| Source | What's read | Rules |
|---|---|---|
| **Page** | a page they publish that someone names (pricing, home) | **robots.txt honoured** (RFC 9309): no robots file → allowed; robots unreachable → not fetched. **Identified user agent** (`MarketingOS-CompetitorWatch/1.0`). **At most once a day.** Only the URL given, never crawled. **Public addresses only**: every redirect hop is checked and private, loopback and metadata addresses are refused. 1.5 MB cap. Only short excerpts are stored (headline, description, headings, prices, offer sentences), never the page itself. |
| **Feed** | their blog or press RSS/Atom feed | robots.txt honoured, every 6 hours |
| **News** | NewsAPI coverage under the names they go by | the existing NewsAPI key, every 12 hours, the last 7 days |
| **Bluesky** | their public posts | the AT Protocol's public API, every 6 hours |

**Nothing is fetched until a person approves the source.** Adding a competitor proposes its page and a news search as sources, unapproved. Owners, admins and marketers manage the watch list; the database enforces this.

**Freshness is never faked:**
- a source that fails is **unavailable**;
- one that has failed for 3 days is **stale**;
- a site that disallows us is **not allowed by the site**.

The page then says "this view may be incomplete" and lists them. The API returns the same list as `limitations`.

## 2. Events: observed, with a source and a time

| Kind | From a page | From news, feeds and posts |
|---|---|---|
| `OFFER_CHANGE` | an offer sentence appears or disappears ("20% off", "free trial", "first box free"…), or the prices change (before/after lists) | price cuts and rises, discounts, promotions |
| `MESSAGING_SHIFT` | headline or description changed (before → after) | rebrand, new slogan, tagline or ad campaign |
| `PRODUCT_LAUNCH` | a new heading like "Introducing…", "Now available" | launches, unveils, debuts, "new … subscription/line/model" |
| `CONTENT_THEME` | — | a term in at least 3 recent posts (30%+ of them), at 3× its earlier share or new |

**Rules that keep events honest:**
- **First read is a baseline.** A page's first fetch only records the starting point; nothing can be said to have changed yet.
- **The article must be about them.** Their name must appear as a whole word ("StrideRun", not "Stride and run"). Coverage that isn't a move (interviews, "best of" lists) is not an event.
- **One story counts once.** Syndicated copies and rewrites are folded into one event:
  - titles are normalised (the "- Outlet" suffix dropped);
  - two titles of the same kind sharing at least half their words, within 7 days, are one story.
  
  The event keeps `reports`, every outlet, and the **original** (earliest) one. Independent signals are stories, not articles.
- **Confidence** depends on where the event came from:
  - 0.9 for their own page;
  - 0.85 for their own feed or posts;
  - 0.7 for a content theme;
  - 0.6 for a news report.

## 3. Insights: what we could do (policy `competitor-v1`, deterministic)

**All four options are always listed**, each with why or why not; NO_ACTION is always on the table. One is recommended, chosen in this order:

| Order | Situation | Recommendation |
|---|---|---|
| 1 | confidence below 0.5, or a single unconfirmed news report | **MONITOR**: wait for a second source or their own channel |
| 2 | none of the organisation's live campaigns is in their market | **MONITOR** (**NO_ACTION** for a content theme) |
| 3 | their offer ended | **NO_ACTION** |
| 4 | a deep offer (30%+ or free) in your market, not shallower than their earlier ones | **RESPOND** |
| 5 | a modest offer | **DIFFERENTIATE**: matching it starts a price war |
| 6 | a product launch | **RESPOND**: buyers will compare |
| 7 | a messaging shift | **DIFFERENTIATE** |
| 8 | a content theme | **MONITOR** |

**Relevance** means the live campaigns in the same market (the competitor's market search term, or their name, in the campaign idea). They're listed on the insight.

**History** compares the event with their moves of the same kind in the last 90 days: how many, how long since the last, and whether a discount is deeper than before.

**Inferred intent** (prompt `competitor.explain` 1.0.0) is a separate section labelled *inferred, not observed*:
- **Format:** 2–3 competing hypotheses, each with what would confirm or rule it out.
- **Input:** the model sees only the observed evidence and is told not to recommend anything or suggest copying their wording.
- **Fallback:** fewer than two hypotheses, or no answer, falls back to generic ones.
- **Limits:** it never decides the recommendation.

**People record what they did:** each insight can be marked *acted on* or *dismissed*, with a note, and this is audited.

**No copying:** competitor text never reaches the ad-writing prompts. The decision engine gets the moves of the last 14 days in the idea's market as `COMPETITOR_MOVE` **review flags** for the Gate 1 approver; the score and outcome are unchanged.

## 4. Forecasts: a measurable target, checked later (model `trend-v1`)

When the competitor's market has a search term, each move (except content themes) stores a forecast; a second move in the same week shares it.

**The prediction:**
- **Target:** the change in Google Trends interest over the next 2 weeks, against the last 4.
- **Model:** `0.25 × last year's change over the same weeks + 0.5 × last week's deviation`.
- **80% range:** from this series' own forecast errors over the past half year, widened by 1.25 (the factor that held on the fitting years).

**Checking it:** when the two weeks are complete, the sweep fetches the series again and records the observed change, the error, whether it fell inside the range, and, for "rise of 10%+" forecasts, whether the rise **materialized**. The page shows each forecast's outcome and the running record.

### Benchmark (`python -m src.eval.competitor_benchmark`)

**The data:**
- five years of weekly interest for 12 category keywords, fetched once and stored in `src/eval/data/trends_weekly.json`, so the numbers are reproducible and tests never call Google;
- the weights and the widening factor were chosen on the first three years;
- the held-out column is the later years only.

**The signal check:** 24 hand-labelled headlines about 3 made-up competitors. It's small, and I wrote it alongside the rules, so treat it as a regression check, not proof of accuracy in the wild.

<!-- benchmark:start -->
**Forecast `trend-v1`**: 12 category keywords, Google Trends, worldwide web search, weekly interest index (0-100), timeframe today 5-y (fetched 2026-10-25). Weights chosen on the first three years; the held-out column is the later weeks only.

| | Fitting years | Held-out years |
|---|---|---|
| Forecasts | 979 | 1198 |
| Mean absolute error of the change, model | 5.1% | 14.9% |
| Mean absolute error of the change, naive "no change" | 5.8% | 17.4% |
| 80% interval contained the outcome | 86% | 76% |
| "Rise of 10%+" calls | 23 | 153 |
| … that came true | 61% | 63% |
| Rises of 10%+ that were called | 17% | 28% |

**Signals**: 24 labelled headlines about 3 competitors.

| | Result |
|---|---|
| Reports of real moves | 18 articles |
| Independent stories (truth) | 8 |
| Stories the engine counted | 8 |
| One story counted twice / two stories merged | 0 / 0 |
| Move type right | 100% |
| Events from articles that weren't a move | 0 |
<!-- benchmark:end -->

**What it says:**
- On years it never saw, the forecast is better than "no change" but far from precise; the range is wide, and that's honest.
- The 80% range holds about three times in four out of sample, a little under its nominal level, so recent years were more volatile than the fitting years.
- Calls of a 10%+ rise come true about 6 times in 10 and catch only a minority of rises: treat them as a weak signal.

## 5. API

- **`GET /v1/market-intelligence/competitors`:** competitors and their sources' health.
- **`GET /v1/market-intelligence/competitors/{id}/signals`:** returns:
  - `signals`: each event, with `observed_or_inferred: "observed"`, its source, times, reports and outlets, plus its `insight` (options, inferred explanations) and `forecast`;
  - `sources`;
  - `limitations`: approved sources that are stale or unavailable.
- **"Scan now"** in the app (worker capability `competitor_scan`): owners, admins and marketers only; robots.txt and every other rule still apply.

## 6. Tests

| Suite | What it proves |
|---|---|
| `tests/unit/test_competitors.py` (36) | **Fetching:** public addresses only (and through redirects); robots.txt by RFC 9309. **Pages:** extraction ignores scripts; first snapshot is a baseline; before/after events for offers, prices, headline and launches; same change is the same story. **News and posts:** classification; whole-word names; syndicated and rewritten reports are one story and join known stories; RSS/Atom; content themes need several posts. **Recommendations:** every policy branch, with all four options. **Inferred intent:** labelled, with fallback, alternatives required. **Forecasts:** have ranges and check dates; no forecast without history; outcome, error and "materialized" when checked. **Robustness:** stale vs unavailable; a failing source never raises; competitor moves are review flags, not score. **Benchmark:** meets its bar. |
| `tests/integration/test_db_competitors.py` (4) | who manages the watch list; sources wait for approval; archiving pauses them; a repeated story adds outlets (the earliest is the original), not events; members read; only the worker records; decisions are audited |
| `frontend/e2e/competitors.spec.ts` (7 × desktop and phone) | the timeline with sources and one story counted once; all four options and inferred intent apart; forecasts and their outcome; stale sources flagged and approval; adding proposes unapproved sources; viewers read only; no sideways scroll at 320 px |

**Live local run** against real public sources (Oatly's homepage, NewsAPI, a public Bluesky account), with no writes to the cloud database:
- **Sources:** all three read correctly; a site that blocks bots (LEGO) was reported as unavailable, not retried around.
- **The changed page** produced an `OFFER_CHANGE` (offer ended → NO_ACTION) and a `MESSAGING_SHIFT` (→ DIFFERENTIATE, since the test campaign was in oat milk), each with 3 LLM hypotheses.
- **Forecast:** a live Trends forecast for "oat milk" was stored (−2.5%, 80% range −30% to +13%, to be checked on 10 Nov).
- **Re-scan:** a third scan added nothing.
