# Agentic Ad Campaign Platform — Build Plan

## Context

Goal: build a portfolio-grade project demonstrating a closed-loop, agentic system that takes an ad campaign from **idea → feasibility scoring → audience generation → creative production → multi-channel launch → metrics-driven feedback → iterative correction → stop**, entirely on free-tier infrastructure. Primary purpose is to be a standout, technically deep artifact for YC-caliber AI/ML job applications — so the design favors *real* external integrations, *real* engagement data, a genuine optimization loop, actual model training/evaluation, and a credible product/business model, not just prompt orchestration.

Decisions locked in with the user:
- **Launch surface:** organic-only — no paid ad spend. Real free-tier channels, real engagement metrics.
- **Scope:** open-ended/ongoing — built in milestones, not a single sprint.
- **Target:** **M1–M6 is the must-finish core.** M7 (fine-tuning), M8 (MCP server), and M9 (stretch) are explicitly out of the current target — optional future work only after M1–M6 is solid and polished, not things to start early or let slow down the core.
- **Orchestration:** LangGraph.
- **Market data & feedback:** real free APIs for market signal + a human-in-the-loop UI for stakeholder feedback.
- **Frontend:** **React via Vite (plain SPA), not Next.js and not Streamlit** — user preference for a more polished, dependency-rich frontend without framework/SSR overhead. Client-side routing (`react-router-dom`), hosted free on Vercel/Netlify as a static build, talking directly to Supabase (JS client + Realtime) for reads/writes under RLS, with two small Supabase Edge Functions as the only backend needed for anything that touches a secret.
- **Stand-out additions (chosen from a brainstorm):** LoRA fine-tuning on the system's own accumulated data, a contextual bandit (LinUCB) instead of a plain bandit, an LLM-as-judge eval harness, a synthetic-persona pre-flight panel, and an MCP server wrapper around the tools.
- **Standalone capability access:** every capability (feasibility scoring, persona generation, image generation, copy generation, each distribution channel, metrics pull) is individually runnable outside the autonomous loop, via a CLI and a frontend "Tools" page — the user isn't forced to hand the whole thing over to full autonomy.
- **Business model / provider tiering (3-tier, multi-tenant):**
  1. **Free tier (default)** — user runs on *our* free API keys, no cost to them.
  2. **Paid-subscription tier** — user pays *us*; we use *our own* paid API keys on their behalf. Billing itself is **stubbed** (a flag/toggle, not real Stripe integration) so build effort stays on the AI/agent engineering rather than payment infra, while still demonstrating the product/business thinking.
  3. **BYOK tier** — user plugs their *own* paid key into the Settings page and gets paid-tier quality without paying us a subscription, since they're covering the API cost directly.
  This requires real multi-tenancy (Supabase Auth + row-level security), not just a single-operator tool.

No existing code exists for this — greenfield build in `~/Personal-projects/ad-campaign-agent` (sibling to existing `manga-portfolio`, `yashas-portfolio`, `AI-CyberSecurityDefencePlatform`).

## Why this architecture (the interview-story angle)

The parts of this system that differentiate it from a generic "LLM wrapper" portfolio project:
1. **Real closed-loop optimization with genuine network effects** — a contextual bandit (LinUCB) picks creative/copy variants using real engagement as reward and audience/channel/domain features as context, not just "LLM regenerates and hopes." It's shared platform-wide (not siloed per user), so one user's success or failure with a given creative archetype improves outcomes for other users in similar domains too — while the domain tag in the context vector keeps it from blindly transferring what worked for one industry onto an unrelated one.
2. **Explainable feasibility scoring** — a transparent weighted composite of real signals (trend momentum, news volume, community interest, retrieved similar-past-campaigns) with an LLM-written rationale, not a black-box number.
3. **Real distribution + real metrics** — actual posts to Bluesky/Reddit and actual emails via Resend, with metrics pulled back from those platforms' APIs, not fabricated.
4. **Human-in-the-loop as a first-class node** — a React approval/feedback gate wired directly into the LangGraph state machine via Supabase (state changes push live through Realtime, not polling), not bolted on.
5. **Actually deployed automation** — a scheduled GitHub Actions workflow drives iteration autonomously, which is a "this runs for real" signal.
6. **Actual model training, not just prompting** — a LoRA fine-tune on the system's own accumulated outcome data is real ML engineering (data → train → eval → deploy), the thing most agent portfolio projects skip entirely.
7. **Engineering rigor around AI quality** — an LLM-as-judge eval harness with a golden set, tracked in CI, catches regressions instead of relying on "it looked fine in the demo."
8. **Ecosystem fluency** — the tools are exposed as an MCP server, usable from Claude Desktop or any other MCP client, not locked inside this one graph.
9. **Real product/business model thinking** — a genuine 3-tier free/subscription/BYOK model with proper multi-tenancy (auth + row-level security), which is exactly the kind of judgment YC evaluates beyond raw ML skill.
10. **A real frontend, not an internal-tool UI** — a React (Vite) app with live realtime updates signals product polish and frontend fluency beyond backend/ML skill alone.

## Free-resource stack

| Concern | Choice | Why free/why this one |
|---|---|---|
| LLM (agents/copy/reasoning) | Groq free tier (Llama 3.3 70B) | Fast, generous free rate limits, great for multi-agent loops |
| LLM (fallback/vision if needed) | Google Gemini 1.5 Flash free tier | Free quota, multimodal |
| Image generation | Pollinations.ai (no key needed) | Fully free, zero rate-limit friction for a portfolio demo |
| Market/trend signal | `pytrends` (Google Trends, unofficial) | Free, no key |
| News/market signal | NewsAPI.org free tier | 100 req/day free |
| Community signal + social channel | Reddit via `praw` | Free API (registered "script" app), real upvotes/comments as metrics — note: Reddit has tightened API terms/pricing before (2023) for high-volume commercial use; a low-volume personal script should stay within free terms, but this is a third-party dependency risk worth knowing about, not something fully in our control |
| Social channel (primary) | Bluesky via `atproto` Python SDK | Fully free read+write API, no app-review gate (unlike X/LinkedIn) |
| Email | Resend free tier | 100 emails/day, clean Python SDK |
| Shared state store + auth | Supabase free tier (Postgres + Auth + Realtime) | Needed because GitHub Actions runners, Vercel, and the browser are all separate machines — SQLite file can't be shared between them, Supabase can. Supabase Auth gives free login/signup + row-level security for multi-tenancy; Realtime gives free live push updates to the frontend |
| Vector store / cross-campaign memory | Supabase `pgvector` extension (same free Postgres instance) | No new service to run — reuses the existing shared DB. Stores embeddings of past ideas/personas/creatives/outcomes for retrieval |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`), run locally/in-runner | Fully free, no API quota consumed, no extra key |
| Graph checkpointing | LangGraph `SqliteSaver`/Postgres checkpointer | Resumable agent state |
| Frontend | Vite + React (SPA) + Tailwind, hosted free on Vercel/Netlify as a static build | Free hosting, realtime-friendly, far more polished/extensible than a Streamlit internal-tool look; no SSR/framework overhead; direct Supabase JS client for reads/writes under RLS |
| Backend/control-plane | Supabase Edge Functions (Deno/TypeScript), free tier | Where secrets are touched (encrypting a BYOK key) and where control-plane actions are dispatched: triggering a GitHub Actions run for a one-off capability, immediately resuming a specific campaign on gate-decision/creation/stop, and logging+redirecting email link clicks (`track-click`) so email engagement doesn't depend on a third party's tracking reliability. Everything else the frontend does is a direct Supabase client call governed by RLS — no separate always-on API server needed |
| Autonomous scheduling | GitHub Actions scheduled workflow | Free minutes on public repo, demonstrates real deployment; also triggerable on-demand from the frontend via an Edge Function calling `workflow_dispatch` |
| Observability | LangSmith free tier | Free tracing for hobby projects, strong "I have observability" story |
| Creative-variant optimization | Epsilon-greedy baseline → **LinUCB contextual bandit**, shared platform-wide (persona/channel/domain-category features as context) | Ships a trivial baseline fast, upgrades to context-aware, cross-user selection without new infra — genuine applied-RL with real network effects, not just prompting |
| Agent quality evaluation | Custom golden set (~15-20 hand-labeled ideas) + LLM-as-judge (Groq/Gemini), run in GitHub Actions on every change | Free CI, no paid eval platform, catches regressions instead of relying on vibes |
| Pre-flight testing | LLM-simulated persona panel (reuses existing personas + LLM) reacts to creative before a real post/email goes out | No new service — reuses tools already built, cheaply filters bad creative before spending a real post |
| Model fine-tuning | LoRA fine-tune via Unsloth on free Google Colab T4 GPU, trained on the system's own accumulated campaign-outcome data | Free GPU, fast/cheap LoRA method, genuine train→eval→deploy pipeline instead of pure API calls |
| Ecosystem exposure | MCP server (Python `mcp` SDK) wrapping `capabilities/` | Free, open standard; makes the toolset usable from Claude Desktop/other MCP clients, not locked to this graph |
| Subscription billing | Stubbed (a `subscriptions` table flag, manually toggleable) — no real Stripe integration | Demonstrates the 3-tier product model without spending build time/scope on real payments, ToS, or support surface area |

Explicitly deprioritized: X/Twitter (free tier read access too restricted for metrics), LinkedIn (posting API requires app review), any paid ad platform, real payment processing (stubbed instead).

## Provider tiering (3-tier: free / our-paid-if-subscribed / user's-own-paid)

Every capability below has a common interface (a small Protocol/ABC) plus a registry that resolves the correct implementation **per logged-in user**. Nodes/capabilities call `get_llm()` / `get_image_generator()` / `get_embedder()` / etc. — they never hard-code a specific vendor client.

| Capability | Free default (tier 1) | Paid upgrade (tier 2/3) |
|---|---|---|
| Core reasoning LLM | Groq Llama 3.3 70B | OpenAI GPT-4o / Anthropic Claude |
| Image generation | Pollinations.ai | OpenAI image gen / Ideogram / Stability |
| Embeddings | `sentence-transformers` (local) | OpenAI `text-embedding-3` / Cohere embed |
| News/market signal | NewsAPI free tier | NewsAPI paid tier / SerpApi |
| LLM-as-judge (eval) | same free LLM as the agents | a stronger paid model as judge — often meaningfully better judging quality even when scoring free-model output |
| Email volume | Resend free tier (100/day) | Resend paid tier |

Precedence per capability, resolved for the current logged-in user:
1. **BYOK (tier 3)** — if the user has their *own* paid key configured on the Settings page (Supabase `provider_keys`, scoped to `user_id`, encrypted), use it. Cost is entirely on the user's own account; they pay us nothing for this capability.
2. **Our-paid-if-subscribed (tier 2)** — else, if the user's `subscriptions` row shows an active (stubbed) subscription, use the **platform's own** paid key — a single shared credential we (the operator) hold in `.env`/a GitHub Actions secret, the same `PAID_<CAPABILITY>_API_KEY` used since M1, now reinterpreted as "the operator's paid credential for subscribers," not a personal fallback. This key is never exposed to users and never stored per-user.
3. **Free (tier 1)** — otherwise, the platform's own free-tier key (`.env`, same as always).

`FORCE_FREE_TIER=true` still overrides everything to free, for demoability.

Rules:
- **Key storage & security:** the Settings page (React) submits a BYOK key to a `submit-provider-key` Supabase Edge Function, which encrypts it server-side with `cryptography`'s Fernet using a `SETTINGS_ENCRYPTION_KEY` that lives only in the Edge Function's environment secrets — the encryption key never reaches the browser bundle, and the frontend never handles encryption itself. The encrypted value is written to a `provider_keys` table (one row per `(user_id, capability)`), protected by row-level security (RLS) so a user can only read/write their own rows. The Settings page only ever displays a masked value (last 4 characters) plus an "update" field; raw key values are never logged. The platform's own tier-2 paid keys live only in `.env`/secrets, never in the multi-tenant DB at all, so there's no path for a user to see another user's key or the operator's own key.
- The active tier per capability is logged (tier name only, never the key) and surfaced as a small status readout in the frontend, so it's always visible which mode a given run used.
- Vector store and distribution channels (Bluesky/Reddit) are not tiered — paid doesn't meaningfully change those, so they stay single-implementation and aren't configurable in Settings.
- Bonus: because the eval harness (M2) already scores agent output quality, it doubles as a way to quantify how much a paid provider actually improves results per capability — a good concrete data point for the README.
- **Open question to resolve during build, not now:** what happens if a free-tier daily cap (e.g. NewsAPI's 100 req/day) is hit mid-run for a free-tier user with no subscription and no BYOK key — retry/backoff, queue to next day, or surface a clear rate-limit error in the frontend. Decide this when building M1/M4; don't block the plan on it.

## Multi-tenancy

Supabase Auth provides login/signup (email+password is enough for a portfolio demo) using its built-in `auth.users` table — no custom user table needed. The React SPA uses Supabase's official JS client (`@supabase/supabase-js`) directly in the browser for login/signup and session handling (session persisted in `localStorage`, no server-side session/cookie complexity since there's no SSR). Every tenant-owned row (`campaigns`, `iterations`, `provider_keys`, `subscriptions`, `capability_runs`, embeddings) carries a `user_id` foreign key to `auth.users`, and Postgres **row-level security (RLS) policies** enforce that a user can only read/write their own rows — this is enforced at the database layer, not just filtered in application code, which is the correct way to do multi-tenancy and worth calling out explicitly in the portfolio writeup. The `CampaignState` passed through the graph carries the owning `user_id` so every capability call resolves providers and stores data against the right tenant.

**Embeddings/memory scope — two separate data flows, resolved explicitly (this was ambiguous before and needs to stay resolved):**
- **Live retrieval + novelty-check (Feasibility Agent step 2, Creative Agent step 5) are strictly per-user, RLS-scoped like everything else.** If User B submits a product idea similar to something User A already ran, User B's agents do **not** see, compare against, or deliberately diversify away from User A's campaign — that would leak one tenant's business content into another tenant's live session, which contradicts the RLS isolation already committed to for `provider_keys`/`subscriptions`. Two users with the same idea each get an independent, cold-start generation grounded only in their own history.
- **The fine-tuning dataset (M7, `export_dataset.py`) is the one place pooling across all users is fine** — it's a training-data export, not a live in-app data flow, so aggregating everyone's outcomes to train a shared model doesn't expose any one user's specific content to another user. This is what actually makes the fine-tune worth doing (more accumulated data), and it's a fundamentally different operation from real-time retrieval.
- **The bandit (`bandit_arms`/context stats) is the deliberate exception — shared platform-wide, not RLS-isolated per user.** This is what lets one user's success (or failure) with a given creative *archetype* — not their literal content — improve outcomes for other users too, the same way trend-following should work. It's safe to share because it never stores raw content: only abstracted style/theme-archetype labels plus a reward, keyed by a context vector that includes a **product domain/category tag** (e.g. fitness, B2B SaaS, e-commerce, food, finance) alongside persona/channel features. Because a contextual bandit generalizes *through its context*, this naturally gives cross-domain safety for free: a style that worked for one fitness brand legitimately informs another fitness brand (similar context → real transfer), while a style that crushed it for fitness but is being considered for enterprise SaaS sits in a different region of context space, so the bandit doesn't confidently recommend it there — no blind copying across unrelated domains, and no special-casing needed. The same logic runs symmetrically for negative outcomes (a theme that flopped in a domain gets suppressed there) since reward-based learning is symmetric by construction.

The `subscriptions` table is intentionally minimal: `user_id`, `status` (`'free'` / `'subscribed'`), toggled manually (e.g. from a small admin script or directly in the Supabase table editor) — clearly documented in the README as a stub standing in for real billing, not a production payment system.

## Implementation specifics (resolved gaps)

These were identified in a pre-build review and resolved here so nothing is ambiguous once coding starts.

**Bandit arm space, context encoding, and reward — concrete definitions, not hand-waved:**
- **Arms:** a fixed catalog, not open-ended LLM-generated styles. 5 image-style archetypes (`minimalist`, `testimonial_social_proof`, `humor_meme`, `urgency_scarcity`, `lifestyle_aspirational`) × 4 copy-tone archetypes (`direct_factual`, `urgency_scarcity`, `humorous`, `aspirational_emotional`) = 20 discrete arms. The Creative Agent's LLM call is instructed to produce creative *within* whichever arm the bandit selects, not to invent a new style each time.
- **Context vector:** a fixed-length numeric encoding, not raw persona text — persona age-bracket (one-hot: `18-24`/`25-34`/`35-44`/`45-54`/`55+`), persona income-tier (one-hot: `low`/`mid`/`high`), channel (one-hot: `bluesky`/`reddit`/`email`), and the product domain/category tag (one-hot, see taxonomy below). Concatenated into one fixed-length vector per (campaign, round, channel).
- **Domain/category taxonomy (fixed, extend later if needed):** `fitness_wellness`, `b2b_saas`, `ecommerce_retail`, `food_beverage`, `finance_fintech`, `education`, `consumer_electronics`, `travel_hospitality`, `real_estate`, `healthcare`, `entertainment_media`, `other`.
- **Reward formula:** per-channel engagement rate normalized to 0–1 (engagement count / impressions-or-recipients where the platform exposes a denominator, e.g. email opens/clicks ÷ recipients; otherwise raw engagement scaled by a fixed cap), combined as an equal-weighted average across the channels that were actually used for that round. Weights live in one constants file so they're easy to tune later, not hardcoded inline.
- **Rejected variants generate no bandit update.** This falls out of the architecture already: a variant that fails the pre-flight panel (step 6) or gets rejected at Human Gate #2 (step 7) never reaches distribution/metrics, so it never reaches the Feedback & Correction Agent (step 10) — the only place the bandit updates. Only variants that actually went out and got real engagement produce a reward signal. No special-casing needed; stated here explicitly so it isn't re-litigated later.

**Retry bounds — both loops that can currently run forever now have a cap:**
- **Novelty-check loop (step 5):** max 3 regeneration attempts; if still too similar to a past creative after 3 tries, proceed with the least-similar of the 3 rather than blocking indefinitely.
- **Pre-flight loop (step 6):** max 3 regeneration attempts; if still scoring low after 3 tries, proceed with the best-scoring of the 3 to Human Gate #2 rather than looping forever — the human gate is the final backstop either way.

**Distribution safety — real accounts, real people, real risk of looking like spam:**
- Use a **dedicated test subreddit you create/moderate** and a **dedicated test Bluesky account** — not personal accounts — so repeated automated posting can't get a personal account flagged or banned.
- **Skip reposting to a channel if the creative hasn't meaningfully changed** since the last round's post to that same channel (compare against the novelty-check embedding distance already being computed anyway) — avoids spamming the same subreddit/inbox with near-duplicates every round.
- **`DRY_RUN=true` env flag** on every `capabilities/distribution.py` function: when set, log the action that *would* have been taken and return a synthetic response instead of actually calling Bluesky/Reddit/Resend. Needed from day one (M1) since local iteration/debugging would otherwise hit real accounts constantly.
- **Idempotency key per (campaign_id, round_id, channel)** on every distribution call, checked against a small dedup table before sending — so a crashed-and-retried GitHub Actions run can't double-post the same round to the same channel.

**Channel account ownership (multi-tenancy limitation — explicit, not implicit, staged deliberately):** for the M1–M6 core, every user's campaigns post through **one shared, platform-owned** Bluesky account, Reddit account, and Resend sender identity — not a per-user OAuth-connected account. This is a deliberate staging decision, not a permanent one: per-user OAuth across three different platforms is real plumbing work with little AI/ML signal, so it's explicitly deferred *until M1–M6 is proven working end-to-end*. Once the core is solid, **per-user connected accounts (each user authenticates their own Bluesky/Reddit/email identity, and their campaigns post under their own name) is the planned next step**, not just a maybe — call it out as a named line item under M9 rather than leaving it vague. Until that lands, the shared-account limitation must be documented plainly in the README the same way the billing stub is, so it doesn't read as an unfinished feature. What *is* per-user and real even in the M1–M6 core: each campaign's **email recipient list** is a field the user provides at campaign creation, not hardcoded.

**Metrics timing:** the Metrics Collector (step 9) waits a fixed window — default 6 hours, aligned with the `campaign-loop.yml` cron cadence — after a round's content goes out before pulling engagement and treating it as that round's observed reward.

**Campaign phase state machine + immediate triggers vs. cron backstop:** a campaign's `status` is one of `created` → `awaiting_gate_1` → `awaiting_gate_2` → `awaiting_metrics` → `awaiting_next_round` (loops back to `awaiting_gate_2`) → `completed` / `rejected`. Steps that don't need to wait for anything (Idea Intake → Feasibility → Audience, and resuming past either gate) should **not** wait for the next scheduled cron tick — that would mean up to a full `METRICS_WAIT_HOURS` delay just to see a feasibility score, which is bad UX for something that has no reason to be slow. Instead: campaign creation, a gate decision being submitted, and "stop campaign" being clicked each **immediately** call a `resume-campaign` Supabase Edge Function, which dispatches `campaign-loop.yml` via `workflow_dispatch` with a `campaign_id` input, processing just that one campaign right away (same mechanism the Tools page already uses for one-off capability runs). The **scheduled cron trigger** (no `campaign_id` input) remains as a reliability sweep: it queries every campaign not in a terminal state and not currently blocked on an undecided gate or an unelapsed metrics timer, and processes each in turn — this is what actually catches a round once its `METRICS_WAIT_HOURS` timer has elapsed (nobody is sitting there clicking anything at exactly that moment), and it's also the backstop if an immediate trigger ever fails to fire.

**Stakeholder free-text feedback → Creative Agent:** free-text feedback (e.g. "tone feels too aggressive") is **not** routed through the bandit's math. It becomes a direct prompt constraint layered on top of whichever arm the bandit selects for the next round's Creative Agent call — the bandit still picks the style/tone archetype from real engagement data; the stakeholder's text just constrains how that archetype gets executed.

**BYOK key failure:** an invalid/expired paid key fails loudly — the capability call errors and the frontend surfaces a clear "your configured key failed" message. No silent fallback to the free tier, since that would mask a paid user's billing/config problem instead of surfacing it.

**Structured output for every bandit-context categorical field:** persona age-bracket, persona income-tier, and the product domain/category tag are all `Literal[...]` fields in their agents' Pydantic output schemas, constrained to the fixed enums defined above — never free-form text that needs parsing afterward. Free text is fragile to bucket reliably; constrained structured output isn't.

**One primary persona drives the loop, not all N.** The Audience Generation Agent (step 3) produces N personas, but exactly one drives each campaign's creative/bandit-context/distribution cycle — running all N in parallel would also multiply real posts per round, compounding the distribution-safety concerns above. The primary persona is the Feasibility Agent's highest-fit persona by default, confirmable/overridable by the stakeholder at Human Gate #1. The rest are stored as reference alternates, not separately acted on.

**Human Gate #1 edit/reject semantics:** "edit" means a direct field overwrite via the frontend form, written straight to Supabase — no agent re-invocation. "Reject" sets `campaign.status = 'rejected'` and ends that graph run with no auto-retry; the user creates a new campaign to try again.

**How gates actually block across ephemeral GitHub Actions runs:** a workflow run can't stay alive waiting on a human decision — it exits. Each `campaign-loop.yml` cron tick loads a campaign's LangGraph checkpoint, checks whether it's currently parked at an undecided gate (Gate #1 or #2), and if so, no-ops for that campaign on this tick. Once the frontend writes a decision row, the *next* cron tick resumes the graph from the checkpoint past that node. This is the actual mechanism behind "blocks graph progression until a decision row appears" — worth being explicit about since it's easy to accidentally build a version that tries to block synchronously inside a single ephemeral run.

**Supabase Realtime must be explicitly confirmed to respect RLS per table**, not assumed — enabling Realtime on a table doesn't automatically inherit that table's RLS policies for the replication/broadcast stream unless configured for it. Verify this during M4 for every table the frontend subscribes to, so a user can't receive broadcast events for another user's row changes even though direct queries are correctly blocked.

**Skip-repost rule vs. reward calculation:** if a channel is skipped for a round (content didn't meaningfully change, per the distribution-safety rule above), that channel is **excluded** from that round's reward average — not backfilled with stale metrics from its last real post. Only channels actually (re)posted-to in a given round contribute to that round's bandit reward.

**Campaign caps (`maxRounds`/`maxDurationMinutes`) are operator-set per tier, not user-configurable — and `maxDurationMinutes` is derived, not hand-picked.** Since free-tier campaigns run on the platform's own shared, rate-limited free API keys (e.g. NewsAPI's 100 req/day is shared across *every* free user), the round cap has to protect that shared resource, not be whatever a given user wants. `maxRounds` defaults: **free tier = 3**; **subscribed (tier 2) and BYOK (tier 3) = 10**, matched between the two per instruction, since a BYOK user is paying their own API cost the same way a subscriber is paying us for ours. `maxDurationMinutes` is **computed from `maxRounds`**, not set as an independent constant — `maxRounds × METRICS_WAIT_HOURS × 60 × buffer_factor` (buffer_factor = 1.5) — so it's a pure safety margin over the round cap's natural completion time and can never end up disproportionate to it (an earlier draft picked the two numbers independently and ended up with free's duration cap looking *tighter* relative to its round count than paid's, which read backwards for a premium tier — deriving it this way makes that class of mistake structurally impossible). With defaults (`METRICS_WAIT_HOURS = 6`): free ≈ 27 hours, subscribed/BYOK ≈ 90 hours (3.75 days) — both proportional, both strictly larger for the higher tier. Framed as pace rather than caps: **every tier runs at the same 4-rounds/day cadence** (`METRICS_WAIT_HOURS` isn't tiered — nobody's rounds run faster or slower per se); the tiers differ only in total rounds allowed (3 vs. 10), i.e. total optimization budget, which is the correct thing for a paid tier to buy more of. The cap is resolved and locked in at campaign creation time from the user's tier *then* — upgrading mid-campaign doesn't retroactively change an in-flight campaign's cap, to avoid mid-run renegotiation complexity.

**Campaign completion produces a closing summary, not just a stopped state.** When a campaign reaches `completed` (stop clicked or a cap hit), the Feedback & Correction Agent's final invocation additionally writes a `campaign_summary`: total rounds run, the winning arm(s) and their final reward, the full per-round reward trend, and total real engagement across channels. The frontend's `CampaignDetail`/Metrics view renders this as the campaign's closing state — needed for the demo video to have something concrete to show ("here's what it converged on and why"), not just an empty "done" badge.

**Subscription tier toggling gets a real one-line admin command, not manual DB editing.** Add an admin subcommand to the existing `cli.py` (e.g. `python -m src.cli admin set-subscription <user_email> <free|subscribed>`) rather than requiring direct Supabase table edits — cheap to add since the CLI already exists, and much better for a live demo than opening a database client on stage.

**Round-trip timing is real and the wait window should be configurable.** Distribute → wait (default 6h) → collect metrics → feedback/bandit update → next round means a 5-round campaign realistically spans a day or more of wall-clock time, not minutes — expected, not a bug, but worth knowing going in. Make the wait an env-configurable `METRICS_WAIT_HOURS` (default 6) rather than hardcoded, so it can be set to a few minutes for local/demo testing.

## Architecture

LangGraph `StateGraph` over a typed `CampaignState` (now carrying `user_id`), with these nodes:

1. **Idea Intake** — normalizes the raw campaign idea into structured fields, including classifying it into a **product domain/category tag** (fitness, B2B SaaS, e-commerce, food, finance, etc. — a fixed taxonomy) used later as a context feature for the shared bandit.
2. **Feasibility Agent** — pulls `pytrends` interest-over-time, NewsAPI headline volume/sentiment (LLM-scored), Reddit search volume/engagement for related keywords, **plus retrieves similar past campaigns from the vector store** as few-shot grounding; combines into a transparent weighted **feasibility/success-likelihood score (0–100)** with an LLM-written rationale.
3. **Audience Generation Agent** — LLM generates N ICP personas (demographics, psychographics, channel fit, messaging angle) as structured Pydantic output, grounded in the feasibility research and any similar past personas retrieved from memory.
4. **Human Gate #1 (React)** — stakeholder reviews idea + feasibility + personas; approve/edit/reject with free-text comments, written directly to Supabase (RLS-protected, no secrets involved so no Edge Function needed). Blocks graph progression until a decision row appears.
5. **Creative Agent** — generates ad image via Pollinations.ai; copy via LLM. Variant selection (image style, copy tone) driven by the **LinUCB contextual bandit** — shared platform-wide across all users, context vector = persona/channel features + product domain/category tag — with a **novelty check** against this user's own embedded past creatives in the vector store (private, per-user) to avoid near-duplicate regeneration.
6. **Synthetic Persona Pre-flight** — the generated creative/copy is shown to an LLM-simulated panel of the approved personas; low predicted engagement sends it back to step 5 for another variant before any real post/email is attempted.
7. **Human Gate #2 (React)** — optional quick approve of the generated creative/copy before it goes out.
8. **Distribution Agents** (parallel) — post to Bluesky, post to Reddit (target subreddit configurable), send email via Resend to a self-curated test list.
9. **Metrics Collector** — polls Bluesky/Reddit APIs for likes/reposts/upvotes/comments; for email, treats click-through as the reliable signal via our own `track-click` redirect endpoint (not solely dependent on Resend's own open/click tracking, which isn't confirmed reliable on the free tier — Resend's own opens are used as best-effort bonus data if present, not relied on). Writes to Supabase.
10. **Feedback & Correction Agent** — compares metrics against target thresholds + any new stakeholder free-text feedback; updates the **shared** bandit arm/context stats (so this outcome improves selection for every user in a similar domain context, not just this one); separately **writes this iteration's idea/persona/creative + outcome as a new embedding into this user's own vector-store row** (private, per-user, so only this user's future campaigns retrieve it); produces a structured revision directive (adjust persona/tone/image style/channel/timing) fed back into step 5.
11. **Loop control** — repeats 5→10 until stakeholder clicks "stop campaign" in the frontend, or a max-iteration/time cap is hit.

State persists in Supabase so the React frontend (reads + Realtime subscriptions, direct writes for gate decisions under RLS) and the GitHub Actions-driven graph runner (read/write) share one source of truth, scoped per-user via RLS. LangGraph's own checkpointer handles mid-run resumability.

**Layering for standalone use:** the actual logic for each capability (score feasibility, generate personas, generate creative, post to a channel, pull metrics) lives in a `capabilities/` module as plain functions with normal typed inputs/outputs (taking `user_id` where provider/data scoping matters) — not tied to `CampaignState`. A LangGraph node is a thin wrapper that reads the relevant fields out of state, calls the capability function, and writes the result back. This means the *same* function backs four different entrypoints:
- the autonomous graph (full loop, no human intervention beyond the gates),
- a CLI (`src/cli.py`) for one-off scriptable calls, e.g. `python -m src.cli feasibility "idea text"` or `python -m src.cli image "prompt"`,
- the frontend's "Tools" page for one-off point-and-click use — it calls a `trigger-capability-run` Edge Function, which dispatches a scoped GitHub Actions run (`capability-run.yml` → `scheduler/run_capability.py`) for just that one capability, writes the result to a `capability_runs` row, and the frontend shows it live via a Supabase Realtime subscription once it completes,
- the MCP server (M8), which wraps these same capability functions rather than raw low-level API clients.

There's exactly one implementation per capability regardless of which surface calls it — no drift between "autonomous mode" and "manual mode." All real agent/AI logic stays Python; the two Edge Functions are deliberately tiny (encrypt-and-store, and dispatch-and-wait) so TypeScript never duplicates any agent logic.

Cross-cutting, not graph nodes:
- **Eval harness** runs offline against a golden set on every push (CI), independent of any live campaign run.
- **Fine-tuned model** (once trained in M7) is swapped in as an optional, cheaper/faster alternative to the LLM call for feasibility scoring and/or copy-quality classification, benchmarked against the LLM baseline via the same eval harness.
- **MCP server** exposes the `capabilities/` layer independently of the graph, for use from external MCP clients (e.g. `score_feasibility`, `generate_creative`, `send_campaign_email` as MCP tools, not raw API pass-throughs).

## Repo layout

```
ad-campaign-agent/
  README.md
  pyproject.toml
  .env.example
  src/
    providers/
      base.py                  # LLMProvider / ImageProvider / EmbeddingProvider / JudgeProvider interfaces
      registry.py               # BYOK (Supabase, per-user) -> our-paid-if-subscribed (.env) -> free (.env) resolution, FORCE_FREE_TIER override
      crypto.py                 # Fernet encrypt/decrypt for provider_keys, using SETTINGS_ENCRYPTION_KEY (also used by the Edge Function equivalent)
      free/                     # Groq, Pollinations, sentence-transformers, NewsAPI free-tier implementations
      paid/                     # OpenAI/Anthropic, OpenAI-image/Ideogram/Stability, OpenAI/Cohere-embeddings implementations
    capabilities/
      idea_intake.py             # normalize_idea(raw_idea) -> structured idea + domain/category Literal tag, plain function
      feasibility.py            # score_feasibility(idea, user_id) -> score + rationale, plain function, no CampaignState
      audience.py                # generate_personas(idea, research, user_id) -> personas
      creative.py                 # generate_creative(persona, variant, user_id) -> image + copy, bandit-driven pick, novelty check
      preflight.py                # score_preflight(creative, personas) -> predicted engagement
      distribution.py             # post_bluesky(...), post_reddit(...), send_email(...) — one function per channel; honors DRY_RUN, enforces idempotency key per (campaign_id, round_id, channel)
      metrics.py                  # collect_metrics(post_refs) -> engagement stats
    cli.py                        # Typer CLI exposing each capabilities/ function as a standalone subcommand, plus an `admin set-subscription <email> <free|subscribed>` command
    graph/
      state.py                # CampaignState schema (Pydantic/TypedDict), carries user_id
      build_graph.py           # StateGraph wiring, edges, loop condition
      nodes/                   # thin wrappers: read state -> call capabilities/* -> write state
        idea_intake.py
        feasibility.py
        audience.py
        human_gate.py
        creative.py
        preflight.py
        distribution_bluesky.py
        distribution_reddit.py
        distribution_email.py
        metrics_collector.py
        feedback_correction.py
    tools/
      trends.py                # pytrends wrapper
      news.py                  # NewsAPI wrapper
      reddit_client.py         # praw wrapper (search + post + metrics)
      bluesky_client.py        # atproto wrapper (post + metrics)
      resend_client.py         # email send + metrics
      image_gen.py             # Pollinations.ai wrapper
      bandit.py                # LinUCB contextual bandit; fixed 20-arm catalog (5 image styles x 4 copy tones), fixed-length categorical context vector (persona age-bracket, income-tier, channel, domain tag)
      memory.py                # embeddings (sentence-transformers) + pgvector read/write, novelty check
    db/
      supabase_client.py
      schema.sql               # campaigns (incl. domain/category tag, email recipient list, status: created/awaiting_gate_1/awaiting_gate_2/awaiting_metrics/awaiting_next_round/completed/rejected, tier-based maxRounds/maxDurationMinutes locked at creation, campaign_summary on completion), iterations, personas, creatives, metrics, feedback, embeddings (pgvector, per-user RLS), provider_keys (per-user, encrypted, RLS), subscriptions (per-user stub flag, RLS), capability_runs (async standalone-run requests/results, RLS), bandit_arms (shared platform-wide, NOT RLS-isolated — 20-arm catalog x context vector), distribution_dedup (idempotency keys per campaign/round/channel), click_log (track-click redirect hits per email link)
    scheduler/
      run_iteration.py         # entrypoint invoked by GitHub Actions for the autonomous loop; queries Supabase for every campaign (any user) due for its next round and processes each in turn
      run_capability.py        # entrypoint invoked by GitHub Actions for a single one-off capability run (Tools page)
    eval/
      golden_set.jsonl         # ~15-20 hand-labeled ideas w/ expected feasibility ranges/persona quality notes
      judge.py                 # LLM-as-judge scorer
      run_eval.py              # CLI entrypoint used by CI
    finetune/
      export_dataset.py        # pulls accumulated outcomes from Supabase into a training set
      train_lora.ipynb         # Unsloth LoRA fine-tune notebook, run on free Colab T4
      evaluate_finetune.py     # benchmarks fine-tuned model against LLM baseline via eval/judge.py
    mcp_server/
      server.py                # MCP server wrapping capabilities/ as tools
  frontend/                     # Vite + React SPA, hosted free on Vercel/Netlify as a static build
    src/
      main.tsx                  # Vite entrypoint
      App.tsx                    # react-router-dom route definitions
      pages/
        Login.tsx                # Supabase Auth login/signup
        Dashboard.tsx             # campaign list, live status via Supabase Realtime
        CampaignDetail.tsx         # gate #1/#2 approve/reject/comment, iteration history, closing summary on completion (route param: campaign id)
        Metrics.tsx                 # unified cross-platform metrics view for a campaign: per-round, per-channel raw counts + normalized reward + which arm was used, reward-trend chart
        Settings.tsx               # BYOK key entry per capability (masked), calls submit-provider-key
        Tools.tsx                  # standalone capability runs, calls trigger-capability-run, live result via Realtime
      lib/
        supabaseClient.ts          # Supabase JS client, session/RLS-scoped to the logged-in user
  supabase/
    functions/
      submit-provider-key/       # Edge Function: encrypts a BYOK key server-side, writes provider_keys
      trigger-capability-run/    # Edge Function: calls GitHub Actions workflow_dispatch for capability-run.yml
      resume-campaign/            # Edge Function: calls workflow_dispatch on campaign-loop.yml with a campaign_id input, for immediate (non-cron) resumption on creation/gate-decision/stop
      track-click/                 # Edge Function: logs an email link click then 302-redirects to the real destination, so email engagement doesn't depend on Resend's own tracking
  .github/workflows/
    campaign-loop.yml          # schedule (no input, sweep every due campaign) + workflow_dispatch (optional campaign_id input, resume just that one immediately) both invoke `python src/scheduler/run_iteration.py`
    capability-run.yml          # workflow_dispatch-triggered `python src/scheduler/run_capability.py` (inputs: capability, user_id, params)
    eval.yml                   # runs `src/eval/run_eval.py` on every push/PR
  docs/
    architecture.md            # diagram + writeup for the portfolio README
```

## Milestones (open-ended build, in order)

**Target: M1–M6 is the must-finish, must-polish core. M7–M9 below are explicitly out of scope for now — don't start them until M1–M6 is done and the portfolio writeup/demo is solid.**

**M1 — Provider abstraction + capabilities layer + core single-shot pipeline (no loop yet)**
Build `providers/base.py` + `registry.py` first (interfaces + free implementations, with `.env` `PAID_<CAPABILITY>_API_KEY` as the platform's own paid source — single-tenant/no user concept yet at this stage). Then build `capabilities/idea_intake.py`, `feasibility.py`, `audience.py`, `creative.py`, `distribution.py` as plain functions (idea → feasibility → audience → creative → distribute once), each calling the provider registry rather than hard-coded clients. `idea_intake.py` classifies the domain/category tag as a constrained `Literal` field from the start, since everything downstream (eventually the bandit context in M6) depends on it being reliable structured output, not free text. `distribution.py` wraps every link in outgoing emails through the `track-click` redirect from day one (so email click data is ours from the first send, not retrofitted later), honors `DRY_RUN`, and enforces the per-(campaign, round, channel) idempotency key from the very first version — cheap to build in now, and necessary so local iteration doesn't hit real Bluesky/Reddit/email accounts while everything else is still being debugged. Wrap them in thin `graph/nodes/` functions and wire `state.py` + `build_graph.py` linearly, skipping gates/pre-flight/bandit/multi-tenancy for now. Add `cli.py` exposing each capability as a standalone subcommand. Manual local trigger for both the graph and the CLI. Verifies every free API integration works end-to-end for one pass: one Bluesky post, one Reddit post, one email, real feasibility score — and that each capability also runs correctly standalone via the CLI, independent of the graph.

**M2 — Eval harness**
Build `eval/golden_set.jsonl`, `judge.py`, `run_eval.py`, and `.github/workflows/eval.yml` so every subsequent change runs against a real quality baseline in CI. Doing this right after M1 (rather than at the end) means every later milestone has a regression check from day one.

**M3 — Human-in-the-loop gates + pre-flight panel**
Add Supabase schema for campaigns/iterations/gates + `supabase_client.py` (single-tenant for now — multi-tenancy comes in M4). Scaffold the `frontend/` Vite + React SPA (no auth yet — a single service-role view is fine at this stage) with a campaign page showing approve/reject/comment for gates #1 and #2, writing decisions directly to Supabase. Wire `human_gate.py` nodes into the graph using the checkpoint-and-no-op pattern (each run checks whether the campaign is parked at an undecided gate and exits early if so, rather than trying to block synchronously) so it actually blocks on a Supabase row until the frontend writes a decision, then resumes from the checkpoint on the next run. Implement edit-as-direct-overwrite and reject-as-terminal-status per the semantics defined in "Implementation specifics." Add `capabilities/preflight.py` (synthetic persona panel) between creative generation and Gate #2.

**M4 — Multi-tenancy + 3-tier provider precedence + Settings (BYOK) + Tools page**
Add Supabase Auth (login/signup) and `user_id`-scoped RLS policies across all tenant-owned tables, explicitly verifying Realtime replication respects RLS on every table the frontend subscribes to (not just direct queries — this doesn't come for free). Add `provider_keys` (per-user BYOK, encrypted), `subscriptions` (per-user stub flag), and `capability_runs` (async standalone-run requests/results) tables. Upgrade `providers/registry.py` to the full 3-tier precedence: BYOK (Supabase, per-user) → our-paid-if-subscribed (`.env`, shared) → free (`.env`, shared). Wire `frontend/src/pages/Login.tsx` using Supabase Auth's JS client to gate the app behind login (a simple protected-route wrapper in `App.tsx`, no SSR needed). Build `frontend/src/pages/Settings.tsx` (BYOK key entry, masked) which calls the new `submit-provider-key` Edge Function to encrypt the key server-side — the encryption key never reaches the browser. Build `frontend/src/pages/Tools.tsx` (standalone capability runs) which calls `trigger-capability-run` to dispatch `src/scheduler/run_capability.py` via the new `capability-run.yml` GitHub Actions workflow, writing its result to `capability_runs`; the frontend shows the result live via a Supabase Realtime subscription once it completes, without affecting any in-progress autonomous campaign. Add the `admin set-subscription` subcommand to `cli.py` alongside the `subscriptions` table itself, so tier-toggling has a real one-line command from the start rather than requiring manual DB edits.

**M5 — Feedback loop + autonomy**
Add `metrics_collector.py` (reading Bluesky/Reddit APIs plus the `track-click` click log for email) and `feedback_correction.py` (including writing the `campaign_summary` closing artifact on completion). Add the loop-control edge back to the creative node, enforcing the operator-set, tier-based `maxRounds` caps (free: 3; subscribed and BYOK: 10) with `maxDurationMinutes` derived from `maxRounds × METRICS_WAIT_HOURS × 60 × 1.5` rather than hardcoded, both locked in at campaign-creation time. Add `run_iteration.py` + `campaign-loop.yml` GitHub Actions workflow supporting both a `schedule` trigger (no input, sweeps every due campaign — the reliability backstop) and a `workflow_dispatch` trigger (optional `campaign_id` input, resumes just that one immediately). Add the `resume-campaign` Edge Function and wire the frontend to call it immediately on campaign creation, gate-decision submission, and "stop campaign" — so those feel responsive rather than waiting on the next cron tick.

**M6 — Contextual bandit + memory/RAG + observability + portfolio polish**
Add `bandit.py` as a simple epsilon-greedy baseline first, then upgrade to a **LinUCB contextual bandit** over the fixed 20-arm catalog (5 image styles × 4 copy tones), stored in the shared (non-RLS) `bandit_arms` table, using the fixed categorical context vector (persona age-bracket/income-tier, channel, domain/category tag) and the normalized per-channel-engagement reward formula — both defined in "Implementation specifics" above — driving creative-variant selection with real engagement as reward — computed only from channels actually (re)posted-to in that round, excluding any skipped channel rather than reusing its stale metrics — shared across all users so outcomes generalize within a domain but not blindly across unrelated ones. Confirm the single-primary-persona rule (highest-fit by default, stakeholder-overridable at Gate #1) is what actually feeds the bandit context, not all N generated personas. Make the metrics wait window an env-configurable `METRICS_WAIT_HOURS` (default 6) rather than hardcoded. Add `memory.py` + `pgvector` schema: embed each completed iteration (idea, persona, creative, outcome) with `sentence-transformers` and write to Supabase, **RLS-scoped per user** (this store stays private, unlike the bandit); wire retrieval into the Feasibility and Creative agents (step 2/5) and the novelty check (step 5), each scoped to that same user's own history. Wire LangSmith tracing across all nodes. Build `frontend/src/pages/Metrics.tsx` — a unified cross-platform view per campaign: per-round, per-channel raw engagement counts, the normalized reward contribution, which of the 20 arms was used, and a reward-trend chart across rounds — plus the `campaign_summary` closing view on completed campaigns. Write `docs/architecture.md` with a diagram, and a portfolio README section: problem framing, architecture diagram, what makes the loop "real" (not simulated), what makes it "learn" (bandit + retrieval memory), what the product/business model is, and a demo GIF/video of the React frontend (the Metrics page is the natural centerpiece of that demo).

---
**Below this line: explicitly out of current target scope (M7–M9). Do not start until M1–M6 is finished and polished.**

**M7 — Fine-tuning pipeline**
Once M5/M6 have produced enough real iteration data in Supabase, build `finetune/export_dataset.py` to curate a training set (idea/persona/creative → feasibility score and/or engagement outcome), fine-tune a small open model with LoRA via Unsloth on a free Colab T4, and benchmark it against both the free and paid LLM baselines using the same `eval/judge.py` harness from M2. If it holds up, register it as a third provider option (alongside free/paid) for feasibility scoring or copy-quality classification.

**M8 — MCP server wrapper**
Build `mcp_server/server.py` exposing the `capabilities/*` functions (score_feasibility, generate_personas, generate_creative, post_bluesky/post_reddit/send_email, collect_metrics) as MCP tools, so the same standalone logic used by the CLI and frontend Tools page is also usable from Claude Desktop or any other MCP client, independent of this project's own graph.

**M9 — Stretch: multi-channel/expansion**
Optional: **per-user OAuth-connected distribution channels** (each user authenticates their own Bluesky/Reddit/email identity so campaigns post under their own name instead of the shared platform account — the planned evolution once M1–M6 is proven, not just a maybe), add more channels, a proper analytics view in the frontend (engagement trend charts per iteration), sandbox ad-platform integration if the user later wants to demonstrate paid-ads API shape, or a real Stripe integration if the stubbed billing ever needs to become real.

## Verification per milestone

- **M1:** run `python -m src.graph.build_graph` locally with one test idea; confirm a real post appears on the test Bluesky/Reddit accounts, a real email arrives, and the feasibility score + rationale look sane against a manually sanity-checked trend (e.g. an idea you know is currently trending vs. one you know isn't). Also confirm the provider registry actually switches: run once with no paid keys set (free path used throughout) and once with a paid LLM key set (paid path used for that capability only), confirming the log correctly reports which tier ran. Separately, run each `cli.py` subcommand standalone (e.g. just `feasibility`, just `image`, just `email`) and confirm each produces a correct real result without invoking the rest of the pipeline. Confirm `DRY_RUN=true` produces logged synthetic responses with zero real posts/emails sent, and confirm calling the same distribution function twice with the same idempotency key sends only once. Confirm a link in a real test email routes through `track-click` and that clicking it both logs the click and correctly redirects to the real destination.
- **M2:** confirm `run_eval.py` produces a score report against the golden set locally, then confirm `eval.yml` runs it automatically on a test PR/push and fails the build if a deliberately-broken prompt regresses the score.
- **M3:** trigger a run, confirm it blocks at the gate (i.e. a run while the gate is still undecided no-ops rather than erroring or hanging), submit a decision in the frontend, confirm the *next* run resumes from the checkpoint and reflects the decision (e.g. edited persona flows through to creative, rejected campaign ends with no retry); confirm the pre-flight panel actually rejects at least one deliberately bad test creative before it would have gone out.
- **M4:** create two test user accounts; confirm each only ever sees their own campaigns/keys (RLS actually enforced — try querying another user's row directly and confirm Postgres denies it, not just the UI hiding it); confirm setting a BYOK key for user A causes their next run to use the paid provider for that capability while user B (no key, no subscription) still runs free; flip user B's `subscriptions` stub flag to `'subscribed'` and confirm their next run uses the platform's own paid key (from `.env`, never visible to them); confirm the Settings page only ever shows a masked key value and that the raw key never appears in any network response after the initial submit; confirm the Tools page's full round trip (Edge Function → `workflow_dispatch` → `capability_runs` write → Realtime update in the browser) completes correctly for a real one-off capability run; confirm user B's browser never receives a Realtime event for user A's row changes (not just that a direct query would fail); confirm `python -m src.cli admin set-subscription <email> subscribed` actually flips that user's tier without needing to touch Supabase directly.
- **M5:** manually `workflow_dispatch` the Actions workflow (with and without a `campaign_id` input) and confirm both the scoped single-campaign run and the sweep-all run work correctly, writing metrics/feedback to Supabase; confirm creating a campaign, submitting a gate decision, and clicking "stop" each trigger `resume-campaign` and produce a near-immediate update in the frontend rather than waiting for the next cron tick; confirm a free-tier campaign actually stops at `maxRounds = 3`, a subscribed/BYOK campaign can run past that up to `maxRounds = 10`, and each tier's `maxDurationMinutes` matches the derived formula rather than an independent hardcoded value; confirm a completed campaign has a populated `campaign_summary`; then enable the cron schedule and let it run unattended for a day, checking the frontend shows iteration history live.
- **M6:** confirm bandit context/arm stats update after each iteration and that variant selection shifts toward the better-performing arm for a given persona/channel/domain context over several iterations; confirm this generalizes **across two different test user accounts in the same domain** (user B's creative selection improves from user A's outcomes when both are e.g. "fitness") but does **not** transfer confidently when the domain differs (a style that won for user A's "fitness" campaign isn't blindly recommended for user B's "B2B SaaS" campaign); separately confirm the `pgvector` memory stays user-isolated — a new campaign's Feasibility/Creative prompts for user B never retrieve or cite user A's past campaigns, only their own; confirm the novelty-check and pre-flight loops each stop after 3 attempts and proceed with the best/least-similar attempt rather than looping indefinitely; confirm a rejected (pre-flight-failed or human-gate-rejected) variant never produces a bandit update; confirm a round where one channel was skipped (unchanged creative) excludes that channel from the reward calculation rather than reusing its old metrics; confirm `METRICS_WAIT_HOURS` set to a low value (e.g. a few minutes) lets a full multi-round campaign be demoed quickly in dev; confirm the Metrics page correctly shows per-round, per-channel real counts alongside which arm was used and the reward trend, matching what's actually in Supabase; confirm LangSmith shows full traces.
- **M7:** confirm `export_dataset.py` produces a non-trivial training set from real accumulated data; confirm the fine-tuned model's eval score (via `eval/judge.py`) is reported side-by-side with the LLM baseline's score, even if it doesn't beat it — the honest comparison is the deliverable, not necessarily a win.
- **M8:** connect Claude Desktop (or another MCP client) to the running MCP server and confirm it can call at least one capability tool (e.g. `generate_creative`) and get a real result back, matching what the CLI/Tools page would produce for the same input.

## Notes for future sessions

- **Target scope is M1–M6.** M7–M9 are explicitly deferred — don't start them, and don't let their existence pull scope/design decisions in M1–M6 toward accommodating them prematurely.
- Start with M1 only — get the free-API plumbing (Bluesky, Reddit, Resend, pytrends, NewsAPI, Pollinations) proven out before adding orchestration complexity. No frontend needed yet at M1.
- M2 (eval harness) is intentionally early, not at the end — it should be the safety net for every milestone after it, not a final polish item.
- M3 is deliberately single-tenant (gates/frontend work for "the" campaign owner, no login); M4 is where multi-tenancy, RLS, BYOK, and the subscription stub get added all at once, since they're one coherent piece of infrastructure. Don't build Settings/BYOK before M4's auth+RLS exists, or it'll need rework.
- All real agent/AI logic stays in Python (`capabilities/`, `tools/`, `providers/`). TypeScript only appears in the frontend and in exactly two small Edge Functions — resist the urge to reimplement any agent logic in TypeScript.
- M7 (fine-tuning) depends on having real accumulated data from M5/M6 — don't start it before there's a meaningful dataset in Supabase.
- The subscription/billing stub is explicitly not real payments — document this clearly in the README so it reads as an intentional scope decision, not an unfinished feature.
- Keep `.env.example` and README API-key setup instructions current as each integration is added, since this is a portfolio repo others (interviewers) may try to read/run. Document both the free-tier keys (required) and the optional paid keys (clearly marked optional, system runs fully free without them) so anyone cloning the repo isn't blocked by missing paid credentials.

## RAG type note (added post-migration)

For the memory/RAG layer in M6: use **plain vector similarity search over `pgvector`** (normal RAG), not agentic RAG or GraphRAG. The retrieval task here — "find the k most similar past campaigns/personas/creatives by embedding similarity" — is a single-hop lookup, not a multi-step or relational reasoning problem, so added retrieval sophistication here would be scope creep on what's meant to be a supporting feature. This project's AI/ML differentiation comes from the bandit, the eval harness, and the fine-tune (M6/M7) — not retrieval complexity.

## CLI removed from the product surface (added post-M6)

`src/cli.py` (the standalone Typer commands referenced throughout this doc — `feasibility`/`personas`/`creative`/`image`/`post-bluesky`/`post-reddit`/`send-email`, plus `admin set-subscription`) has been deleted. Decision: a real product doesn't ask its user to open a terminal to operate it — everything the CLI covered now has a frontend equivalent that's actually used:

- Standalone capability testing → the Tools page (`trigger-capability-run` Edge Function + `capability-run.yml`), already existed alongside the CLI and now covers this alone.
- Campaign creation → the Dashboard's Create Campaign form, calling a new `create-campaign` Edge Function that dispatches `run_campaign.py` via `campaign-loop.yml`'s `workflow_dispatch` (mirrors how `resume-campaign` already dispatched gate-decision/stop resumption).
- `admin set-subscription` is the one exception with no frontend equivalent, since it's an operator billing action, not something an end user does to themselves. It's now `src/admin/set_subscription.py`, a plain standalone script — still not part of the product's own UI, run directly by the operator when needed.

`src/graph/run_campaign.py`, `src/scheduler/run_iteration.py`, and `src/scheduler/run_capability.py` are unaffected — they were always backend worker scripts invoked by GitHub Actions, not "the CLI" in the sense removed here. The "Layering for standalone use" section above and the M1 repo layout's `cli.py` line are now historical — accurate to what M1 built, superseded by this decision.
