# Changelog

All notable changes to MarketingOS. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). One version covers the Python
backend and the frontend (`pyproject.toml` and `frontend/package.json` must
match; the release workflow checks).

To release: move the **Unreleased** entries under a new version heading, bump
both version fields, commit, then push a tag `vX.Y.Z`. The
[release workflow](.github/workflows/release.yml) publishes that section as the
GitHub Release notes.

## [Unreleased]

### Added
- **Competitor intelligence** (`capabilities/competitors.py`, migration `20261026000200_competitor_intelligence`, prompt `competitor.explain` 1.0.0, [docs/COMPETITOR_INTELLIGENCE.md](docs/COMPETITOR_INTELLIGENCE.md)):
  - **Watch list:** an organisation lists competitors and approves the public sources to watch: pages they publish, their feed, news coverage, public Bluesky posts. Nothing is fetched until a source is approved.
  - **Polite, safe fetching:** robots.txt honoured (RFC 9309), an identified user agent, at most daily for pages, public addresses only through every redirect, and short excerpts stored, never whole pages.
  - **Observed events:** offer changes, messaging shifts, product launches and content themes, each with quotes (before/after), source URL, outlet and times.
    - A page's first read is a baseline.
    - Coverage that isn't about them, or isn't a move, is ignored.
    - Duplicate and syndicated reports are one story, with every outlet and the original listed.
  - **Insights (`competitor-v1`, deterministic):** RESPOND, MONITOR, DIFFERENTIATE or NO_ACTION, with all four options and their reasons, confidence, the live campaigns affected and how the move compares with the competitor's history.
    - Inferred intent comes from the LLM as labelled hypotheses with alternatives; it never picks the recommendation.
    - People mark insights acted on or dismissed (audited).
  - **Forecasts (`trend-v1`):** each move stores a forecast of the market's search interest over the next two weeks with an 80% range, checked against what happened when it's due (error, inside the range, did the rise materialize).
  - **Benchmark** (`python -m src.eval.competitor_benchmark`):
    - forecasts on 5 years of Trends data for 12 markets: 14.9% error on held-out years against 17.4% for "no change", with the 80% range holding 76% of the time;
    - signals: 18 reports of 8 stories counted as 8, with no false events.
  - **Source health:** stale, unavailable and robots-blocked sources are shown as limitations, never as current data.
  - **Decision engine:** recent competitor moves in the idea's market become `COMPETITOR_MOVE` review flags at Gate 1; the score is unchanged and no competitor text reaches the ad prompts.
  - **Where it appears:**
    - the "Competitors" page (timeline, insights, forecasts and their track record, sources, "Scan now");
    - the API `GET /v1/market-intelligence/competitors` and `…/competitors/{id}/signals`.
    
    Translated into 5 languages.
- **Proof of impact: did the campaign cause anything?** (`capabilities/impact.py`, migration `20261026000100_experiments`, [docs/PROOF_OF_IMPACT.md](docs/PROOF_OF_IMPACT.md)):
  - **Pre-registered experiments:** before the first email, a campaign's audience can be run as a randomized experiment.
    - The design is declared up front: hypothesis, primary metric (qualified sign-ups by default), a holdout control group that gets nothing, the attribution window, and a fixed-horizon stopping rule.
    - A sample-size plan shows whether the list is big enough.
    - The design locks at the first send (database trigger).
  - **Stable assignment:** the arm is a hash of the experiment and the address, stored on first use, so retries, resumed runs and later rounds never move anyone.
  - **Sending:** the control group is never emailed. Treatment emails go one per person, each with its own link token and idempotency key, so nobody sees other recipients' addresses.
  - **Outcomes:** exposures, clicks (`track-click` credits the person and passes `ciq_t` to the site) and conversions (`POST /v1/conversions`, matched by token or hashed address, de-duplicated by `event_id`), each with a source and a time.
  - **Analysis (`impact-v1`):**
    - intention-to-treat;
    - Newcombe 95% interval for the absolute lift;
    - P(campaign helped);
    - relative lift only with a supported baseline;
    - extra conversions and revenue caused;
    - a sample-ratio check.
    
    Observed counts, the causal estimate and click-attributed revenue are kept apart.
  - **Verdicts:** `COLLECTING` (interim, no verdict, so no peeking), then at the predeclared end `POSITIVE_IMPACT`, `NEGATIVE_IMPACT`, `NO_MEANINGFUL_IMPACT` or `INCONCLUSIVE` with a reason (insufficient data, no outcome data, sample-ratio mismatch, interval too wide).
  - **Learning:** a valid final result feeds the bandit once, with the reward defined as the primary metric credited to the latest email before it.
  - **Fixed-horizon runs:** the A/B test's Bayesian early stop waits while an experiment runs.
  - **Where it appears:**
    - the campaign page's "Proof of impact" panel: setup, verdict, interval charts, observed table, revenue, data quality and freshness, assumptions, design;
    - the API `GET /v1/experiments/{id}/impact`, `GET /v1/campaigns/{id}/experiment` and `POST /v1/conversions`;
    - the MCP tool `measure_impact`.
    
    Translated into 5 languages.
  - **Benchmark** (`python -m src.eval.impact_benchmark`): 9 synthetic scenarios with known truths, 400 experiments each. In the no-effect scenarios with usable data, the engine claimed an effect 5.2% of the time; the point estimate and before/after did so 99% of the time. It catches broken assignments and missing conversion data every time.
- **Brand reputation circuit breaker** (`capabilities/circuit_breaker.py`, migration `20261025000400_circuit_breaker`, [docs/CIRCUIT_BREAKER.md](docs/CIRCUIT_BREAKER.md)):
  - **Triggers (deterministic):**
    - an expired offer (`offer_ends_at`);
    - a definitely broken CTA link (no host, 404 or 410; a timeout isn't enough);
    - live copy breaking a hard rule (such as a word banned after approval);
    - Gate 2 approvals no longer meeting the quorum;
    - crisis words next to the topic in 2+ separate news headlines;
    - a person's emergency stop.
  - **When it checks:** in the hourly sweep, right before each send (cached for 5 minutes) and in the daily market watch.
  - **Enforced in the database:**
    - `claim_delivery()` refuses every send while a critical hold is active and stores it as `held`, for the whole campaign or one channel;
    - a row lock makes a pause racing a send win once it commits;
    - one active hold per campaign, trigger and channel;
    - the sweep skips paused campaigns, and held sends never count as posts.
  - **People:**
    - owners, admins and approvers can pull an emergency stop or revoke an approval, with a reason;
    - only owners and admins resume or mark a false alarm, with a note;
    - resuming re-queues held sends, which are checked again before they go;
    - every action is audited.
  - **Where it appears:**
    - a paused panel leading the campaign page (trigger, channel, evidence and its freshness, the suggested response);
    - safety controls (offer end date, stop, revoke, hold history);
    - a Paused pill on the Dashboard;
    - notifications with how many sends are waiting;
    - the API `GET /v1/campaigns/{id}/holds` and `POST /v1/campaigns/{id}/circuit-breaker/evaluate`.
    
    Translated into 5 languages.
- **Campaign crash test: how could this ad fail?** (`capabilities/crash_test.py`, graph node `crash_test`, migration `20261025000300_crash_tests`, prompts `crashtest.simulate` 1.0.0 and `crashtest.revise` 1.1.0, [docs/CRASH_TEST.md](docs/CRASH_TEST.md)):
  - **Rule checks (`rules-v1`, deterministic):** before Gate 2, every ad (post, on-image headline and button) is checked for:
    - invented testimonials and ratings (FTC 16 CFR 465);
    - fake social proof and false urgency (FTC dark-patterns report);
    - personal-attribute questions (Meta ad standards);
    - numbers not in the brief, unsupported claims, policy blocks and a broken link.
    
    The brand's own words are exempt, and only rule checks can be critical.
  - **Simulated scenarios (`marketing-risk-v1`):** 8 situations in one LLM call (skeptic, price-sensitive buyer, a competitor's 20% off, an ad-standards reviewer, a 3-second scroll, a sensitivity read, the wrong audience, a non-native reader).
    - Findings must quote the ad's exact words.
    - They are capped at high and labelled simulation, not real customers.
  - **Revise and re-test:** high or critical findings get a revised version, re-tested on the same checks and scenarios, showing what was resolved, what remains and what's new.
    - The revision may not invent facts or grow longer; a much longer one is asked again.
    - "Use the revised version" puts it in through the copy history and redraws the ad from its template and stored background, with no new image generation.
  - **Gate 2 rule:** approving an ad whose current crash test is critical needs a written reason (database trigger).
  - **Storage:** reports are stored (`crash_tests`) and audited.
  - **Where it appears:** Gate 2 report with the problems marked in the ad, a chip per round, the Tools page "Crash-test an ad", the MCP tool `crash_test_ad`, and the API `GET`/`POST /v1/campaigns/{id}/crash-tests`. Translated into 5 languages.
  - **Benchmark** (`python -m src.eval.crashtest_benchmark`) over 28 ads: the rule checks catch 22/22 planted problems with 0 false alarms on 6 clean ads; the old brand-safety checks alone caught 6/22.
  - **Supporting change:** the painted background of a scene template is now stored with the ad (`round-N-scene.jpg`), so it can be redrawn with new words.
- **Decision intelligence: knowing when not to advertise** (`capabilities/decision.py`, graph node `decide`, migration `20261025000200_campaign_decisions`, [docs/DECISION_ENGINE.md](docs/DECISION_ENGINE.md)):
  - **What it recommends:** before Gate 1, every campaign gets a recommendation of LAUNCH, TEST_SMALL, WAIT, KILL or INSUFFICIENT_EVIDENCE. It's deterministic (no LLM), so a recommendation can be reproduced from its stored inputs snapshot and policy version (`decision-v1`).
  - **Hard blocks first:** prohibited products, unsupportable claims, banned words and a broken CTA link. No score overrides them; the campaign stops as the new status `blocked`, which the database won't let anyone approve.
  - **Six-factor scorecard:** demand, momentum, purchase intent, competition, audience reach and track record.
    - Each factor records its source, fetch time and reliability (measured, proxy or estimate).
    - Missing or stale evidence raises the uncertainty instead of counting as zero.
  - **What each outcome does:**
    - TEST_SMALL caps the campaign at 2 rounds.
    - WAIT is re-evaluated by the daily market watch once search interest reaches its threshold, and approvers are notified.
    - Approving against a KILL, WAIT or INSUFFICIENT_EVIDENCE recommendation needs a written reason, enforced by a database trigger.
  - **Storage:** decisions are stored and audited (`campaign.decision`), and the campaign's eventual outcome is written back to the decision.
  - **UI:**
    - Gate 1 leads with the decision card: verdict, score, uncertainty, reasons, the evidence for each factor, and the baseline comparison.
    - A blocked campaign shows why.
    - The Dashboard shows each campaign's verdict.
    - The Tools page has "Should we advertise?".
    - All of it is translated into 5 languages.
  - **Access:** MCP tool `evaluate_decision`. API: `GET /v1/campaigns/{id}/decision`, `POST /v1/decision-engine/evaluate` and `GET /v1/decision-engine/evaluations/{id}`.
  - **Benchmark** (`python -m src.eval.decision_benchmark`) over 25 hand-labelled scenarios against "launch whenever feasibility ≥ 40":

    | | Decision engine | Old rule |
    |---|---|---|
    | Matches the expected decision | 96% | 28% |
    | Hard-blocked campaigns launched (of 6) | 0 | 4 |
    | Weak opportunities spent on (of 5) | 0 | 2 |
  - **Supporting changes:**
    - Feasibility signals now carry a fetch time.
    - Bluesky and Mastodon searches keep a sample of post texts for purchase intent (kept out of the LLM prompt).
    - A blocked campaign no longer counts toward the active-campaign limit.
- **Product-first ads with 34 industry templates** (`tools/ad_templates.py`, `tools/product_cutout.py`, `capabilities/product.py`, migration `20261025000100_product_photo`, prompt `creative.generate` 2.0.0, [docs/AD_TEMPLATES.md](docs/AD_TEMPLATES.md)):
  - **Campaign form:** a product photo is now required when creating a campaign; a tagline and a link are optional.
    - The photo uploads to a private `product-photos` bucket, into the user's own folder.
    - `create-campaign` checks that the path belongs to the caller, plus the tagline length and the link scheme.
  - **Real product in every ad:**
    - The photo is cut out once per campaign with rembg (optional extra `ads`; the model is cached in Actions).
    - It is set into the ad as the hero. If the cut-out fails, the photo goes on a card instead.
  - **34 templates** in the bandit's five image-style families (7 + 8 + 7 + 6 + 6), from a study of 128 real ads and template systems.
    - 26 draw their background in code and make no image-model call. 8 have FLUX paint a background with an empty spot.
    - Common layout rules: safe margins, one call to action, at most one badge, the logo on every ad, at most two type families.
    - New OFL fonts: Anton, Montserrat, Pacifico, Caveat.
  - **Template choice:** the creative LLM picks the template within the bandit's style and fills its words (eyebrow, benefits, steps, stat, badge) only from the idea.
  - **No invented claims:** the prompt forbids invented customer names and quotes, reviews, statistics, prices, discounts and deadlines.
  - **Gate 2 "New picture"** keeps the template and words: it repaints the background, or moves to the next drawn colour/arrangement variant.
  - The campaign page shows which template a round used.
- **Mastodon as a posting channel** (`graph/nodes/distribution_mastodon.py`, migration `20261024000300_mastodon_channel`):
  - Every approved round is also posted to Mastodon with the finished ad (alt text = its headline), through the same exactly-once delivery ledger, retries and DRY_RUN as Bluesky. An `Idempotency-Key` per campaign/round stops a retried request posting twice.
  - Switched on only by `MASTODON_POST_TOKEN` (scopes `write:statuses` + `write:media`); the existing read-only search token never posts.
  - Guardrails: 500-character limit; the short disclaimer and the brand-kit sign-off are added when they fit.
  - Metrics: favourites, boosts and replies (shown as likes, reposts, replies) → reward capped at 50, like Bluesky. The bandit reads Mastodon as a short-form social feed, sharing Bluesky's context slot, so the stored arm matrices keep their size.
  - Campaign rounds link to the post ("Mastodon ↗"); the dashboard shows a Mastodon tile once there are Mastodon metrics. Privacy page updated.
- **Images that look like ads** (`tools/ad_composer.py`, prompt `creative.generate` 1.3.0):
  - **Finished layout:** the picture is cropped to the feed format (1080×1080, or a 1200×628 banner), and a headline and a call-to-action button in the brand-kit colour are set over a soft dark fade at the bottom. The face is the site's Fraunces. Output is JPEG so it stays under Bluesky's image size cap.
  - **Five layouts, one per bandit image style**, so the bandit also learns which layout works:
    - *Lifestyle:* soft dark fade, elegant white headline, brand-colour button.
    - *Minimalist:* a calm off-white band on top with lighter dark type and an outlined button; the picture below has no fade.
    - *Testimonial:* the headline in italics under a large brand-colour quote mark. No star rating or attribution, since those would claim reviews the brand hasn't shown.
    - *Humor / meme:* a big outlined caption across the top and a white button.
    - *Urgency:* a slanted brand-colour band with heavy type and a dark button. No invented deadline or "limited" tag.
    - Headlines are balanced across lines (no lone last word).
  - **The copy step writes them:** the creative prompt now also returns a `headline` (at most 8 words) and a `cta` (2-4 words) in the campaign language. Either one is dropped if it uses a banned or brand-forbidden word.
  - **Ad-style visuals:** the image brief asks for an advertising photograph with one focal subject, a clean background, a calm lower third for the headline, and no text in the picture.
  - **Limits:** text in scripts the font can't set without shaping (Hindi, Arabic, emoji) is left off rather than drawn as boxes. Templates used for outpainting (paid tier) get no text on top. A layout failure ships the bare picture rather than failing the round.
- **Better free image models** (`providers/free/cloudflare_image.py`, `hf_image.py`, `gemini_image.py`): FLUX.1-schnell on Cloudflare Workers AI first (free daily allowance), then on Hugging Face, then Gemini (needs billing), then Pollinations. Each failure hands over to the next, and a provider that's out of credit or unauthorised is skipped for the rest of the run.
- **Brand logo on every ad** (Settings → Brand kit, `components/BrandLogo`, private `brand-logos` bucket, `brand_kits.logo_path`, migration `20261024000200`): owners and admins upload a PNG, JPEG or WebP (up to 1 MB); it goes on a small white chip in the corner each layout leaves free.
- **The ad goes out in emails too** (`resend_client.py`, `distribution.with_ad_image`): embedded inline (`cid:`), not linked, so it never expires; clicking it follows the call-to-action link. Email templates can place it with `{{image}}`. A/B variant B's email carries variant B's own ad (it was generated before but unused). Retried emails keep their image.
- **Gate 2 shows the finished ad, with "New picture"** (`components/NewPicture`, capability `ad_image`): the ad sits at the top of the gate with its headline, button and layout beside it. Approvers can repaint the picture (same prompt, words, layout and brand) up to 5 times per round; approving sends the latest one. The job checks the caller may approve the campaign, and only runs while that round waits at Gate 2. New columns `iterations.headline`, `cta` and `image_version`.
- **Demo script** (`docs/DEMO.md`) and **README screenshots** (`docs/screenshots`, refreshed by `frontend/e2e/screenshots.spec.ts` against demo data; no image generation used).
- **OpenAI images on a switch** (`OPENAI_IMAGE_GEN`, off by default): with `OPENAI_IMAGE_GEN=on` (repo variable in CI) the platform's `OPENAI_API_KEY` makes images with `gpt-image-2`, ahead of the free chain. Kept off to save its credit.
- Pollinations' corner watermark is cropped off its pictures.

### Fixed
- **Campaign emails no longer show every recipient's address.** Each recipient now gets their own email, instead of one message with the whole list in "To".
  - Each email has its own Resend idempotency key, so a retry after a partial failure never emails anyone twice.
  - Sends are paced to Resend's rate limit.
  - Deliveries already queued in the old format still replay as before.
- **No duplicate posts or emails after a timed-out send.** A send can time out after the provider already accepted it, and a retry then posted twice.
  - Emails now carry a Resend idempotency key per campaign/round/variant.
  - Before any repeat Bluesky attempt, in-process or scheduled, `deliver()` reconciles: it looks for our own post with exactly that text and records it instead of posting again.
  - If it can't tell, it doesn't resend; the attempt is rescheduled.
  - Mastodon already sent an `Idempotency-Key`.
- **One channel's metrics outage no longer loses the others.** Each channel is collected on its own. A channel that can't be read is "not measured" (left out of the reward), never a zero, and a failed metrics write still counts for the round.
- **A/B split no longer alphabetical:** recipients are split by a hash of campaign + address. The split is stable for a campaign (retries never move anyone) and independent between campaigns; halves differ by at most one.
- **Bayesian A/B read-out is stable with a zero baseline:**
  - The headline number is now the absolute difference in click rate (`expected_difference`).
  - Relative lift is reported only when A has clicks, as the posterior median.
- **Bandit updates can't overwrite each other:** an arm's write is compare-and-swap on its pull count, with a re-read and retry. A learning step that still fails is logged without failing the round.
- **A round with zero engagement on every channel no longer stops the campaign:** it's treated as too little evidence. The next round tries another angle, and the round and time caps still apply. This is what ended the 2026-10-24 smoke-test campaign after round 1.
- **LLM fallbacks were never used in production:** the `llm_fallback` switch defaults to on, but with no row in `feature_flags` the database answered "off". A flag with no row now keeps its default, so Gemini (and Cerebras/OpenRouter when keys are set) take over when Groq is rate-limited.
- **Campaigns never got their link:** the Dashboard form and `create-campaign` never passed the call-to-action link through, so posts and emails carried none and email clicks couldn't be counted. The link is now a composer field.
- **Security:** the campaign and Tools workflows pasted user-typed inputs (the idea, Tools parameters) straight into their shell scripts. A crafted idea could therefore run commands on the runner, where the secrets are. Inputs now arrive as environment variables.
- A dropped database connection while claiming a delivery lost that round's post or email ("delivery ledger unavailable"); the claim is now retried like the send.
- The finished ad's caption no longer covers its button; the regenerated preview keeps its note.
- "Interview Maya," lost its stray comma when a persona's name contains one.
- Pollinations returned the same picture for the same prompt; each call now uses a fresh seed.
- Security: Vite 8.2.1 → 8.3.5 (dev-server advisories; `npm audit` now clean).
- OpenAI images (paid tier and BYOK) failed every time: `gpt-image-2` rejects the `response_format` parameter, which is no longer sent.
- **The finished ad is stored** (private `ad-images` bucket, `iterations.image_path`, migration `20261024000100`): the campaign page shows the exact image instead of re-drawing a preview from the prompt. Only people who can view the campaign can read it. Older rounds keep the preview.

- **3D persona figures** on campaign persona cards and Tools → Personas results:
  - **The set:** 20 archetypes (teacher with books, doctor in a white coat with a stethoscope, chef, developer, …), each with a female and a male stylised 3D character. They live in `frontend/public/personas/<archetype>-<gender>.webp` and are re-rendered with `frontend/scripts/render_personas.py`.
  - **Choosing a figure:** the personas prompt (`audience.personas` 1.2.0) gives each persona an archetype and a gender, so the figure always matches the persona the AI wrote.
  - **Older personas:** the archetype falls back to keywords in the name and description. Gender falls back to the pronouns in the description and is never guessed from the name.
  - **No clear gender:** the card shows initials instead of a figure.
  - **Storage:** new `personas.archetype` and `personas.gender` columns (migrations `20261022000900`, `20261022001000`).
- **App sidebar** (`components/AppSidebar`, `lib/shell.ts`): one place for every feature on all signed-in pages.
  - **Desktop:** a slim icon rail on the left that slides out to full labels when the cursor (or keyboard focus) reaches it.
  - **Phones:** a drawer opened from the top bar's new menu button.
  - **Contents:** New campaign, Dashboard, Calendar, Tools, Run history, Playbooks, Our AI model, Settings (with its sections nested, the one in view underlined), Admin (operators), Docs, System status and Contact.
  - **What moved:** the top bar keeps the logo, language, theme and account; its page links moved into the sidebar. The Settings sections drawer is replaced by the nested list.
- **Automatic playbooks** (`capabilities/playbooks.py`, prompt `playbook.write` 1.0.0, `playbooks` table, `/playbooks`):
  - **When they're written:** when a campaign finishes, its organisation's playbook for that industry is rewritten from every measured round.
  - **What's in them:** the best and worst copy tones and visual styles (computed from rewards), plus round reviews and focus-group quotes, turned into a headline, do / avoid, audience notes and the next thing to test.
  - **How they're used:** new creatives in that industry are written with it (prompt `creative.generate` 1.2.0).
- **Bayesian A/B testing with early stopping** (`experiments.bayesian_ab`, `campaigns.ab_decision`):
  - **The read-out:** email A/B rounds now report "92% chance B beats A", with the expected lift and a 95% interval.
  - **Early stopping:** once either variant is at least 95% likely to be better, with 10 or more people per variant, the split stops and the winner's style runs for everyone from the next round. An `experiment.decided` webhook event is sent.
- **Market-moment alerts** (`scheduler/market_watch.py`, `market_alerts`, `campaigns.market_watch`):
  - **The baseline:** feasibility saves each campaign's search keyword and launch-time signals.
  - **The check:** the hourly sweep re-checks live campaigns about daily. A Google Trends or news-coverage spike (1.5× / 2× the baseline) raises an alert on the Dashboard (live) and the campaign page, sends Slack/email and fires a `market.moment` webhook. Alerts can be dismissed.
- **Brand & compliance radar** (replaces the brand-safety box):
  - **Four areas:** safety, claims, readability and accessibility, each clear / to review / blocked.
  - **Fixes:** every finding comes with a suggested fix.
  - **New checks (advice, never blocking):** comparative claims, an English reading-ease score and long sentences, emoji overload, all-caps words, and lower-case multi-word hashtags.
- **Interview your personas** (`persona-chat` Edge Function, `components/PersonaChat`):
  - **What it does:** "Interview <name>" on every persona, both campaign and Tools. The persona answers in character, grounded in its profile and the campaign idea, in the campaign's language, with suggested questions.
  - **Where answers come from:** a BYOK key when the user has saved one, otherwise Groq's free tier within the organisation's daily AI budget. Usage is logged to `llm_usage`.
  - **Limits and storage:** 20 questions per persona per person per day. Chats live in `persona_chats`, readable only by their author.
  - **Setup:** needs the `GROQ_API_KEY` function secret.
- **Synthetic focus group before Gate 2** (`capabilities/focus_group.py`, prompt `focus_group.react` 1.0.0, `iterations.focus_group`):
  - **What it does:** all of a campaign's personas react to the final draft (would click / scroll past / object, with a click chance and a one-line quote). The approver sees this "Audience verdict" at Gate 2 and on each round.
  - **Safety:** advice only. A failure never blocks the gate.
- **"Why this ad?" and "What MarketingOS has learned":**
  - **Recorded reasoning:** the bandit records its reasoning when it picks an arm (`bandit.explain_choice`, `iterations.arm_explain`). That covers expected reward against the exploration bonus, explore vs exploit, the runners-up and how many rounds back it.
  - **Per round:** each round shows this as evidence/exploration bars.
  - **On the Dashboard:** the learned panel turns measured results into sentences per industry (for example, which copy tone or visual style beats the average), plus the size of the shared learning loop.
- **Model card** (`/models`, `model_versions` table, `model_card()`):
  - **What it shows:** our fine-tuned domain classifier against its base model on the hand-labelled and held-out test sets, plus speed and cost, common confusions, the Gate 1 correction loop, live deployment (shadow/canary, agreement) and version history.
  - **Updates:** the weekly retrain now records each promoted version.
- **Tools run history** (`/tools/history`, linked from the Recent runs sidebar):
  - **Search:** across inputs, results, persona names and errors.
  - **Filters:** tool, status, language, and when (today, 7/30 days, a month, a year, or a custom range).
  - **Results:** grouped by month; a run opens back in Tools. The Tools input now clears after Run.
- **Page loader** (`lib/loading.ts`, `components/PageLoader`, `LoaderMascot`):
  - **Look:** a frosted, blurred cover while a page or its first data loads, so half-loaded pages never show. The MarketingOS robot is animated in SVG: the growth swoosh draws round, the bars rise, the megaphone broadcasts, and it bobs and blinks. The caption walks through the product (scoring, personas, creative, measuring).
  - **Timing:** it appears only after 150 ms and stays at least 400 ms.
  - **Failures:** it steps aside on a failed load so the Retry toast can be used.
- **Rotatable 3D persona figures** on the campaign page and in Tools → Personas:
  - **Viewer:** each persona's model stands above its info card with no background. Drag or use the arrow keys to turn it; it spins slowly when idle and pauses while held. It's lazy-loaded with three.js and only drawn while on screen.
  - **Models:** `frontend/public/personas/models/<role>-<gender>.glb`, made from the 2D figures with Microsoft's TRELLIS demo on Hugging Face (`frontend/scripts/make_persona_models.py`, needs `HF_TOKEN`). The 2D figure is shown until a model exists.
  - **Layout:** three personas side by side on desktop (2 on tablets, 1 on phones). Feasibility moved into a full-width card above them.
- **App-wide toasts** (`lib/toast.ts`, `components/Toaster`, helpers in `lib/notify.ts`):
  - **Placement and look:** bottom-right on desktop, full width on phones. A plain card where only the icon tile carries the colour, with a pausable countdown line.
  - **Behaviour:** identical messages are de-duplicated, and errors are announced right away (success and info politely).
  - **Coverage:**
    - Results of actions across Dashboard, Campaign detail, Tools, Settings (keys, templates, username, team, approvals, brand kit, API & webhooks, billing, privacy), Admin, Audit log, Comments, Copy editor and invitations.
    - "Copied" confirmations.
    - Offline / back-online notices.
    - A "Couldn't load — Retry" toast when a page's data fails to load.
  - **Stays inline:** field validation, login results and page states.
- **Dashboard reorganised** into four labelled groups, with no gaps between panels. Panels in a row stretch to the same height, and the shorter side fills with useful content.
  - **Start a campaign:** a full-width spotlight composer. Today's plan limits and upgrade link sit along its bottom.
  - **Performance:** every metric in one place. The KPI cards, then reward over time (with rounds measured, average and latest reward) beside engagement by channel and winning creative arms.
  - **Campaigns:** a full-width table. A pipeline strip on top shows every status and filters the table, and status pills show in full.
  - **Help & activity:** a new Help & resources panel (walkthrough, docs, system status, contact support, shortcut) beside recent activity. A Help button in the header jumps to it.
  - **Phones:** the KPIs show as a 2 × 2 grid.
- **Collapsible sidebars** (`components/SideDrawer`): Tools → Recent runs (right) and the Settings sections list (left) are closed by default.
  - **Opening and closing:** a tab on the screen edge (a floating button on phones) opens them over the page, and Esc or a click outside closes them.
  - **Recent runs:** the tab shows the run count and pulses while a run is in progress.
  - **Settings sections:** the section in view keeps the site's orange text and left-to-right underline.
- **Remove a saved provider key** in Settings → Provider keys; its Vault secret is deleted with it.
- **Onboarding checklist** on the Dashboard: 6 steps worked out from real data, dismissible.
- **Public docs** (`/docs`).
- **Public status page** (`/status`): fed by an `uptime.yml` workflow that probes the site, database API, sign-in and Edge Functions every 15 minutes, showing 24-hour and 7-day uptime and 48-hour hourly bars.
- **Internal admin console** (`/admin`, platform operators added with `python -m src.admin.make_admin`):
  - **What's there:** a health overview, organisations with plan overrides, a dead-letter retry, feature flags and audit-chain verification.
  - **Safeguards:** every action is audited, and there's no impersonation.
- **Stripe billing** (test mode until live keys are set):
  - **Upgrade:** owners upgrade through Stripe Checkout and manage billing in the customer portal.
  - **Webhook:** a signature-verified `stripe-webhook` drives plans through `apply_billing()`.
  - **Settings:** a new Plan & billing section.
- **Public REST API** (`api` Edge Function, `docs/openapi.yaml`):
  - **Keys:** organisation API keys with read/write scopes, stored hashed, with a 60/min rate limit.
  - **Endpoints:** list, read and start campaigns, and read usage.
- **Webhooks:**
  - **What's sent:** any audit event can go to HTTPS endpoints, HMAC-SHA256 signed.
  - **Delivery:** the first attempt goes out instantly from the database (`pg_net`), and the sweep retries for about 10 hours.
  - **UI:** Settings → API & webhooks, with a test button and recent deliveries.
- **Campaign calendar** (`/calendar`):
  - **Month grid:** starts, sent rounds and results due for the active organisation.
  - **Waiting on approval:** the list of open gates.
  - **Portfolio:** a table with status, rounds, best reward and last activity.
- **Collaboration:**
  - **Discussion:** a live comment thread on each campaign, optionally tied to a round.
  - **Copy editing:** approvers can edit variant A or B at Gate 2, with a version history that keeps the AI draft and allows restoring any version. What's sent is what was approved.
- **Email A/B tests:**
  - **Opt-in** per campaign, from a composer toggle.
  - **Two variants per round:** each round writes variant B with the bandit's second-best style, in its own graph step before Gate 2.
  - **Split send:** the recipient list is split deterministically in two, with separate click tracking for each half.
  - **Significance:** a two-proportion z-test picks a winner only when p < 0.05.
  - **Learning:** the bandit learns from both arms. Results appear on the Metrics page.
- **Brand kit** per organisation (Settings → Brand kit):
  - **Creative:** generation follows the kit's voice and preferred words. The creative prompt moves to 1.1.0, unchanged when no kit is set.
  - **Guardrails:** forbidden words act as banned terms.
  - **Sending:** the required sign-off or hashtag is added to posts and emails.
- **Model registry for the domain classifier:**
  - **Pinned version:** the live Hugging Face revision is recorded, and the retrain registers each promotion.
  - **One-command rollback** to the previous revision.
  - **Shadow mode:** a candidate runs alongside the live model, with only content-free agreement logged.
  - **Canary:** a stable percentage of ideas use the candidate.
  - **CLI:** `python -m src.finetune.deployments`.
- **Prompt registry** (`src/prompts`):
  - **Versioned prompts:** all 8 production prompts are in one place with IDs and semantic versions, moved over word for word. A test fails if a prompt's text changes without a version bump.
  - **Recorded per call:** each LLM call stores its prompt version in `llm_usage.prompt` and Langfuse.
  - **Eval regression gate:** the eval now also fails when any metric falls more than 5 points below the accepted baseline (`src/eval/baseline.json`).
- **Observability:**
  - **Sentry** error tracking for the workers and the browser, with a crash-recovery screen.
  - **Langfuse** tracing: each run shows every graph step as a span and every LLM call as a generation with tokens, latency and fallbacks. Prompt text is excluded unless opted in.
  - **In-app panel:** "AI usage & reliability" for managers.
  - All of it is optional and switches on only when keys are set.
- **GDPR self-service** (Settings → Privacy & data):
  - **Export:** a full JSON download of your data (`export_my_data()`).
  - **Deletion:** account deletion through the `delete-account` Edge Function. Team campaigns pass to another owner, and the last owner of a team with other members is blocked.
  - **Retention:** an automatic job (`apply_retention()`, hourly sweep).
  - The privacy policy is updated to match.
- **Approval flows:**
  - **Votes:** approvers vote on each gate, and the database decides it once the organisation's required number of approvals (1–5) is reached; any reject rejects it. Direct gate updates are removed, so the quorum can't be bypassed.
  - **Org policy:** an optional ban on approving your own campaign, plus approval deadlines with an escalation to managers.
  - **Notifications:** Slack webhook and email (opt-in) when a gate opens.
- **Themed dropdowns** (`components/Select`) replace every native `<select>`, whose open list was drawn by the operating system. Keyboard and screen-reader support follow the WAI-ARIA combobox pattern.
- **Signed-in end-to-end tests** with a mocked backend (`e2e/app.spec.ts`).
- **Plans and usage limits** per organisation (free / pro / enterprise):
  - **Hard limits,** enforced by database triggers: campaigns per day, active campaigns, team size and Tools runs per day. `create-campaign` checks them before dispatching.
  - **Daily AI token budget,** measured from `llm_usage`: the worker pauses an organisation's runs for the day once it's spent.
  - **Dashboard** usage meters.
- **Tamper-evident audit log:**
  - **Recording:** database triggers record campaign, gate, membership, invitation, organisation, BYOK-key, delivery and feature-flag changes, with the actor.
  - **Integrity:** rows are hash-chained and append-only for every role; `verify_audit_chain()` finds the first broken row.
  - **Access:** org managers can browse and export it (CSV/JSON) in Settings.
- **Organisations and roles:**
  - **Roles:** owner, admin, marketer, approver and viewer, enforced by RLS and checked membership functions. Marketers can't approve their own campaigns.
  - **Invites:** single-use, email-bound invite links that expire after 7 days.
  - **Personal orgs:** every user has one, and existing campaigns moved into them.
  - **UI:** an organisation switcher in the account menu, a Team section in Settings, and role-aware buttons.
- **BYOK keys in Supabase Vault:** keys are stored and read only through service-role database functions; `provider_keys` holds a pointer and the masked key. Includes a one-off migration for legacy AES keys (`src/admin/migrate_keys_to_vault.py`).
- **Brand-safety and regulatory guardrails** (`src/capabilities/guardrails.py`):
  - **Automatic rewrites:** copy linking anywhere but the campaign's own domain, or containing personal data, banned terms (`BANNED_TERMS`) or more than Bluesky's 300 characters, is rewritten, up to 2 times.
  - **Gate 2 review:** absolute and regulated claims (health, finance, fitness) are flagged there.
  - **Disclaimers:** regulated categories get a disclaimer on email (full) and on Bluesky (short, when it fits).
  - **Send-time check:** sending re-checks the final copy and refuses anything still blocked.
- **Prompt-injection protection** (`src/security/prompt_guard.py`):
  - all user and third-party text in LLM prompts is fenced as data, with a system-prompt rule never to follow instructions found inside it;
  - news headlines that read like instructions are dropped before they reach the model;
  - hidden control and bidi characters are stripped;
  - off-list category answers fall back to `other` instead of crashing the run.
- **Delivery ledger** (`deliveries` table, atomic `claim_delivery()`): each campaign/round/channel is sent exactly once, even across runs and concurrent workers. Failed sends are retried in-process, then rescheduled with backoff by the hourly sweep, and moved to a dead-letter state with an ops alert after 5 attempts. A channel outage no longer crashes a campaign run.
- **LLM gateway** for the free tier: automatic failover from Groq to Cerebras, OpenRouter or Gemini (whichever keys are set) on rate limits or outages. Failing providers are benched, and every call's tokens and latency are recorded in `llm_usage`.
- **Feature flags** (`feature_flags` table, `src/flags.py`, `useFlag()`): kill switch, allow list and a stable percentage rollout. A single SQL rule serves both the backend and the browser.
- **Test suite:** Python unit tests (no network), RLS and feature-flag integration tests against a Postgres built from the migrations, and Playwright end-to-end tests on desktop and phone. All run free in CI on every push.
- **Database migrations** with the Supabase CLI (`supabase/migrations`). The baseline is a dump of production. Every change is checked on a fresh database, and migrations and Edge Functions deploy from main.

### Fixed
- **Dashboard loads in one round trip** (its seven queries now run in parallel).
- **Security: `bandit_arms` (the shared learning model) is now protected by row-level security.** Before, it had no RLS and full grants for anon/authenticated, so anyone with the public anon key could rewrite or wipe it. Now signed-in members can only read it, and only the workers write it.
- **Campaigns no longer end after round 1 when nothing was measured** (DRY_RUN, or no delivery went out). The continue/stop step treated "no data" as a zero score; such rounds now continue (round and time caps still apply). Found in smoke test #10.
- **The loader, photo captions and the campaign preview badge are actually blurred now.** The CSS minifier kept only the `-webkit-` prefixed `backdrop-filter`, so Chrome applied no blur at all.
- **Ad copy with long links wraps** instead of widening the campaign page on phones.
- **Feedback fixes:**
  - A failed gate vote no longer shows in success green.
  - Brand-kit and approval-policy saves now look different on success and on failure.
  - A failed comment keeps its text.
  - Admin "verify audit" no longer crashes when the request fails.
  - A failed campaign or metrics load no longer shows "not found".
  - About 25 actions that failed silently now say so.
- **Removed the coloured side-stripe styling** from notices and the ad-copy block (now an evenly bordered quote panel).
- **No sideways scrolling on phones and tablets:**
  - **Top bar:** its page links now share the screen width.
  - **Dashboard:** the campaign table's search and status tabs wrap.
  - **Settings:** the section links and the team, API-key and webhook lists fit the screen, and long URLs and keys in code wrap.
  - **Regression test:** a new e2e test (`e2e/no-sideways-scroll.spec.ts`) checks every page at 320–768 px with long content.
- **Security:** users could UPDATE their own `provider_keys` rows (`for all` RLS policy). They can now only read and delete them.
- **Duplicate protection reset between runs.** The local JSON dedup file didn't survive between GitHub Actions runs (each starts on a fresh machine), so it only prevented duplicates within one run.
- **Live updates never arrived.** The Realtime publication contained no tables, so Dashboard, CampaignDetail and Metrics only refreshed on reload.
- **Sideways scroll at 430 px:** the Login page (OAuth buttons) and the public navbar were too wide.

## [0.8.0] - 2026-10-21

### Added
- **M8: MCP server** (`src/mcp_server`). Ten capability tools for Claude Desktop, Claude Code and any MCP client, with safety annotations. Sends are dry runs by default, and campaign tools only return the caller's own campaigns.
- **M7: fine-tuned domain classifier.** Qwen2.5-1.5B + LoRA, distilled from the production LLM and served on CPU with llama.cpp: golden-set accuracy went from 56% for the base model to 83% fine-tuned.
- **M7: human corrections and a weekly retrain.** Gate 1 category corrections become training labels. A weekly retrain on a Kaggle GPU promotes a new model only if it isn't worse on any quality gate.
- **Frontend redesign** ("Signal" design system), public pages (About, Contact, Privacy, Terms, 404), usernames and an account menu, a mobile layout pass, and the brand logo.
- **Deployed** to Vercel.

### Fixed
- Edge Functions rejected the browser's CORS preflight.
- Intermittent 401s right after sign-in (Auth/PostgREST clock skew).
- Groq retired `llama-3.3-70b-versatile`; the app now uses `openai/gpt-oss-120b`.

## [0.6.0] - 2026-08-14

### Added
- **M6:** LinUCB contextual bandit over 20 creative archetypes, per-user memory and RAG with pgvector, and a novelty check.
- **M5:** metrics, feedback and an autonomous loop with round and time caps, plus campaign summaries.
- **M4:** multi-tenancy with RLS, 3-tier provider resolution (BYOK → subscribed → free), and the Settings and Tools pages.
- **M3:** human-in-the-loop gates, a synthetic-persona pre-flight panel, and the React frontend.
- **M2:** LLM-as-judge eval harness on a golden set, run in CI.
- **M1:** capability layer: feasibility from live signals, personas, creative, and Bluesky and email distribution with dry runs and dedup.

[Unreleased]: https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform/releases/tag/v0.8.0
[0.6.0]: https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform/releases/tag/v0.6.0
