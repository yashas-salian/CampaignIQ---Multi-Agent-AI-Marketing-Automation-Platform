# Agentic Ad Campaign Platform

Closed-loop, agentic system that takes an ad campaign from idea → feasibility
scoring → audience generation → creative production → multi-channel launch →
metrics-driven feedback → iterative correction → stop, entirely on free-tier
infrastructure. Full design and milestone plan: [`DESIGN.md`](./DESIGN.md).

**Status:** M1–M6 (the full "must-finish core" per [`DESIGN.md`](./DESIGN.md))
built and live-verified: provider abstraction, eval harness, human-in-the-loop
gates + pre-flight panel, multi-tenancy + BYOK + Tools page, the metrics →
feedback → autonomy loop, and a contextual bandit + per-user memory/RAG.
Beyond the core: M7 (a fine-tuned domain classifier with a weekly retrain on
human corrections) and M8 (the capabilities as an MCP server). M9 (stretch) is
out of scope for now.
Architecture diagram + what makes this more than an LLM wrapper:
[`docs/architecture.md`](./docs/architecture.md).

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -e .
copy .env.example .env   # then fill in the free-tier keys below
```

Required free-tier keys (the system runs fully free without any paid key):

| Key | Where to get it |
|---|---|
| `GROQ_API_KEY` | console.groq.com |
| `NEWSAPI_KEY` | newsapi.org |
| `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` | bsky.app Settings → App Passwords |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `RESEND_TEST_TO_EMAIL` | resend.com |

**Reddit is on hold** (API access blocked by policy changes) — `REDDIT_*`
keys and `ENABLE_REDDIT` still exist in `.env.example` but aren't required;
all Reddit code (feasibility signal + `post-reddit` distribution) stays in
the repo, just unused by default. Set `ENABLE_REDDIT=true` once creds are
available again.

Feasibility's community signal is now sourced from **Bluesky search**
(reuses your posting creds, no setup) plus optionally **Mastodon search**
(`MASTODON_ACCESS_TOKEN`, optional — see below).

Optional paid keys (`PAID_LLM_API_KEY`, `PAID_IMAGE_API_KEY` — both OpenAI)
upgrade the LLM/image-gen tier; leave blank to stay on the free tier.
`FORCE_FREE_TIER=true` forces free providers even if paid keys are set.

### Community signal (feasibility scoring)

`score_feasibility` combines Google Trends + NewsAPI + a "community" signal
into its 0-100 score. The community signal is Bluesky search by default
(works immediately, same creds as posting). Mastodon search is a second,
optional input — but **it only activates once `MASTODON_ACCESS_TOKEN` is
set**: unauthenticated search against a public instance (default
`mastodon.social`) returns empty results for any keyword on most instances
(confirmed — even common words return nothing without a token), so it's
skipped by default rather than silently dragging every score toward zero.
To enable it: on your chosen instance's web UI, go to Settings →
Development → New Application, create one, and copy the access token it
generates (no review/approval process).

### Distribution safety

`DRY_RUN=true` (the default) makes every `capabilities/distribution.py`
function log what it *would* send and return a synthetic result — no real
Bluesky/Reddit/email calls. Set `DRY_RUN=false` to actually send. Every
distribution call also takes a `campaign_id`/`round_id` and goes through the
**delivery ledger** ([`capabilities/delivery.py`](./src/capabilities/delivery.py),
`deliveries` table). It guarantees the following:
- **Once per round:** the same campaign/round/channel is sent at most once, even across separate GitHub Actions runs or two workers at the same time (atomic claim).
- **A failing channel can't crash a run:** it's retried three times in-process, then rescheduled with backoff (5 min, 30 min, 2 h, 8 h) by `src.scheduler.retry_deliveries`, which runs in the hourly sweep.
- **Dead-letter state:** after 5 attempts the send is marked `dead`, and `OPS_ALERT_EMAIL` gets an alert.
- **No ledger, no send:** a send never happens without a ledger claim.

Without Supabase credentials (local scripts), a local JSON file stands in for the ledger.

### Brand-safety guardrails

[`src/capabilities/guardrails.py`](./src/capabilities/guardrails.py) checks every generated creative. It's deterministic and free, with no LLM call.

| Severity | Triggers | What happens |
|---|---|---|
| **block** | A link to anything but the campaign's CTA domain, an email address or phone number, a banned term (built-in list + `BANNED_TERMS`), over 300 characters for Bluesky, empty copy | The copy is regenerated with the reasons, up to 2 times. If it's still blocked, Gate 2 shows why and distribution refuses to send. |
| **review** | Absolute claims ("guaranteed", "risk-free", "#1", "clinically proven") and category-specific claims ("cures", "guaranteed returns", "lose 10 kg") | Shown at Gate 2 for the approver to substantiate. |

Healthcare, finance and fitness campaigns automatically get a disclaimer: the full text on emails, and a short form on Bluesky when it fits. Results are stored per round in `iterations.guardrail_flags`.

### Prompt-injection protection

Untrusted text reaches the prompts from two places:
- **Third parties:** news headlines feed the feasibility rationale.
- **Users:** the idea, stakeholder comments and past campaigns, plus model output derived from them (personas, copy) that gets passed to the next step.

[`src/security/prompt_guard.py`](./src/security/prompt_guard.py) handles both:
- **Fencing:** every untrusted value goes inside an `<untrusted source=... id=random>` block, and fake closing tags inside the value are neutralised. Every system prompt adds the rule that fenced text is data, never instructions.
- **Clean-up:** control and bidi characters are stripped, and length is capped.
- **Filtering:** headlines that read like instructions ("ignore previous instructions", role tags, "reveal your prompt", …) are dropped and logged.

Outputs are schema-checked: an off-list category becomes `other`, and personas and the bandit use fixed label sets. That limits what a successful injection could change.

### `track-click` (email link tracking)

Outgoing emails route their CTA link through a Supabase Edge Function so
click data doesn't depend on Resend's own tracking. This is Supabase
infrastructure pulled forward from M3 — a full Supabase project with
auth/RLS/campaigns tables isn't set up until then, just this one function:

1. Create a free project at supabase.com and apply the schema (see
   [Database and Edge Functions](#database-and-edge-functions)).
2. Deploy the `track-click` function
   ([`supabase/functions/track-click/index.ts`](./supabase/functions/track-click/index.ts)).
3. Set `TRACK_CLICK_BASE_URL` in `.env` to
   `https://<project-ref>.supabase.co/functions/v1/track-click`.

Without this set, `send-email --cta-url` still works but links go out
unwrapped (no click tracking) rather than breaking.

## Using the app

Everything happens in the browser — creating a campaign, approving gates,
stopping a campaign, and one-off capability testing. There is no CLI in the
product surface; `src/graph/run_campaign.py`, `src/scheduler/run_iteration.py`,
and `src/scheduler/run_capability.py` are backend worker scripts, invoked
automatically by GitHub Actions when a frontend action dispatches one of the
Edge Functions below — you never run them yourself.

- **Create a campaign**: Dashboard → fill in the idea + target language →
  "Create campaign". This calls the `create-campaign` Edge Function, which
  dispatches `campaign-loop.yml` to run `run_campaign.py` for you. The
  campaign appears in the Dashboard once feasibility scoring completes.
- **Approve/reject a gate**: open the campaign, use the Approve / Approve
  with edits / Reject buttons. This writes the decision and immediately
  calls `resume-campaign`, which dispatches the same workflow to pick up
  right where the graph paused — no waiting for the hourly cron sweep.
- **Stop a campaign**: "Stop campaign" on the campaign's detail page — same
  immediate-dispatch mechanism.
- **One-off capability testing** (no full campaign): the Tools page —
  feasibility / personas / image, via the `trigger-capability-run` Edge
  Function and `capability-run.yml`.

`DRY_RUN=false` in `.env` (local) / the `DRY_RUN` repo secret (GitHub
Actions) controls whether distribution calls actually hit Bluesky/email/
Reddit or just log a synthetic result — see "Distribution safety" above.

### Edge Functions to deploy

Deployed by [`supabase-deploy.yml`](./.github/workflows/supabase-deploy.yml) (see [Database and Edge Functions](#database-and-edge-functions)); JWT verification is configured per function in `supabase/config.toml`, and is off only for `track-click`, since email clients follow the link unauthenticated:

| Function | Source | Needs |
|---|---|---|
| `track-click` | `supabase/functions/track-click/index.ts` | — |
| `submit-provider-key` | `supabase/functions/submit-provider-key/index.ts` | — (stores keys in Supabase Vault) |
| `trigger-capability-run` | `supabase/functions/trigger-capability-run/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |
| `resume-campaign` | `supabase/functions/resume-campaign/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |
| `create-campaign` | `supabase/functions/create-campaign/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |

`GITHUB_REPO`/`GITHUB_PAT` are shared across the last three (same repo, same
PAT, only set once). The GitHub Actions side needs every key in `.env`
mirrored as a repo secret (Settings → Secrets and variables → Actions) —
`campaign-loop.yml` and `capability-run.yml` both list exactly which ones
in their `env:` blocks.

## Database and Edge Functions

The schema lives in [`supabase/migrations/`](./supabase/migrations/), managed with the Supabase CLI (a frontend devDependency: `npx --prefix frontend supabase ... --workdir .`). [`20261021000000_baseline.sql`](./supabase/migrations/20261021000000_baseline.sql) is a `supabase db dump` of production; it replaces the hand-run `src/db/schema_*.sql` files.

- **New schema change:** `npx --prefix frontend supabase migration new <name> --workdir .`, write the SQL, and push. Never edit an applied migration.
- **Every change** is checked by [`supabase-check.yml`](./.github/workflows/supabase-check.yml), which builds a fresh database from all migrations in Docker and lints it. It never touches production.
- **On main,** [`supabase-deploy.yml`](./.github/workflows/supabase-deploy.yml) applies pending migrations to production (`SUPABASE_DB_URL`; must be the IPv4 Session-pooler string) and deploys the Edge Functions (`SUPABASE_ACCESS_TOKEN` + `SUPABASE_PROJECT_REF`, skipped until they're set). The first run records the baseline as already applied instead of re-running it.
- **Fresh project** (staging, a new environment): `supabase db push --db-url <its connection string>` builds everything, including the signup trigger on `auth.users`.
- **Locally:** `npx --prefix frontend supabase db start --workdir .` (needs Docker) gives a throwaway Postgres on port 54322 with every migration applied.

## Organisations and roles

Campaigns belong to an **organisation**. Every user has a personal one and can create team organisations (Settings → Team).

| | owner | admin | marketer | approver | viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| See campaigns, results, members | ✓ | ✓ | ✓ | ✓ | ✓ |
| Create, run, stop campaigns | ✓ | ✓ | ✓ | | |
| Decide gates, pick personas, correct categories | ✓ | ✓ | | ✓ | |
| Invite, change roles, remove members | ✓ | ✓ | | | |
| Grant owner or admin, remove admins | ✓ | | | | |

- **Separation of duties:** marketers can't approve their own campaigns.
- **Where it's enforced:** in the database. RLS on every campaign table goes through `org_can()` and `campaign_can()`, and memberships only change through checked functions (`create_invitation`, `accept_invitation`, `set_member_role`, `remove_member`), which never let an organisation lose its last owner. The UI only hides what a role can't use.
- **Invites:** single-use links, bound to the invited email address, that expire after 7 days. Only a hash of the token is stored. If the invitee isn't signed in, the link survives the sign-in redirect.
- **Still per user:** BYOK keys and templates.

## Plans and usage limits

Each organisation has a plan. A personal organisation follows its owner's subscription, and team plans are set by billing or the admin console; members can't change them. Limits live in `plan_limits`, where null means unlimited:

| | free | pro | enterprise |
|---|---|---|---|
| Campaigns per day | 3 | 50 | ∞ |
| Active campaigns | 3 | 25 | ∞ |
| Members | 5 | 50 | ∞ |
| Tools runs per day (per user) | 20 | 500 | ∞ |
| AI tokens per day | 150k | 3M | ∞ |

- **Hard limits** are enforced by triggers on `campaigns`, `memberships` and `capability_runs`, with the error `usage limit: …`.
- **Checked before spending anything:** `create-campaign` calls `campaign_quota_error()` before dispatching and returns 429, because the campaign row is only written after the first LLM calls.
- **Token budget:** the gateway tags every LLM call with the run's organisation (`llm_usage.org_id`). Once the daily budget is spent, the worker skips that organisation's runs until the next day; the check fails open, so it can never block a run by mistake.
- **Dashboard:** the plan card shows the active organisation's usage.

## Audit log

`audit_log` is written by **database triggers**, so no path (frontend, workers, Edge Functions, the SQL editor) can skip it.
- **What's recorded:** campaign creation, status changes, stops and category corrections; gate decisions with comments; members added, re-roled or removed; invitations created, accepted or revoked; organisation renames; BYOK keys added, rotated or deleted (capability and masked key only); deliveries sent or dead-lettered; feature-flag changes. Each event records who did it, or `system` for workers.
- **Integrity:** every row stores the SHA-256 of the previous one, so `verify_audit_chain()` (service role) returns the first row whose hash doesn't match, or null when the chain is intact. A trigger blocks UPDATE, DELETE and TRUNCATE, and no role can write the table directly.
- **Access:** org owners and admins browse and export it as CSV or JSON in Settings → Audit log.
- **Never logged:** secrets, invite tokens and delivery payloads.

## LLM gateway (free-tier fallback)

Free-tier LLM calls go through [`src/providers/gateway.py`](./src/providers/gateway.py), which tries each provider in order: Groq, then whichever of **Cerebras** (same `gpt-oss-120b` model), **OpenRouter** (`gpt-oss-120b:free`) and **Gemini Flash** has an API key set. All three have free tiers; see `.env.example`.

- **Failover:** a rate limit, outage or bad key moves the call to the next provider and benches the failing one: an hour when its daily budget is spent, a minute for a per-minute limit, 30 s for an outage.
- **Fast switching:** with fallbacks configured, Groq retries only twice, so a spent budget fails over in seconds instead of waiting out Groq's retry-after.
- **Usage accounting:** every call is recorded in `llm_usage` (provider, model, tokens, latency, errors). Users can read their own rows. Recording is best effort and never slows or breaks a run.
- **BYOK and paid users** don't go through the gateway: their prompts stay with the provider they chose.
- **Kill switch:** the `llm_fallback` flag, or `FLAG_LLM_FALLBACK=false`.

## Feature flags and releases

**Flags** (`feature_flags` table) let new code ship dark and turn on without a deploy.
- **Per flag:** a kill switch (`enabled`), an allow list of user ids, and a percentage rollout. Each user gets a stable bucket, so raising the percentage never drops anyone who was already in.
- **One rule for both sides:** the SQL function `feature_enabled_for()` is the only evaluator, called by Python's `src.flags.is_enabled(key, user_id)` and the browser's `useFlag(key)`.
- **Overrides:** `FLAG_<KEY>=true|false` overrides a flag in Python, for tests, local dev, or killing a flag without a DB write.
- **Failures:** a failed lookup returns the caller's default, so a flag can never break a run.
- **Changing flags:** users can read flags but not change them. Edit them with the service role (SQL Editor, or the admin console later).

**Releases:** one version covers the backend and the frontend (`pyproject.toml` and `frontend/package.json`), and the footer shows it.
- [`CHANGELOG.md`](./CHANGELOG.md) follows Keep a Changelog.
- Pushing a tag `vX.Y.Z` runs [`release.yml`](./.github/workflows/release.yml). It checks that the tag and both version fields agree, then publishes that version's changelog section as the GitHub Release.

## Tests

[`tests.yml`](./.github/workflows/tests.yml) runs on every push. It's free: no Groq, no live Supabase.

| Suite | What it covers | Run locally |
|---|---|---|
| **Python unit** (`tests/unit`) | LLM-JSON repair, BYOK crypto, provider tiers, feasibility weighting and graceful degradation, DRY_RUN and dedup, click tracking, LinUCB, graph routing, Gate 1 category corrections, the M7 retrain gate, and the MCP server (in-memory client) | `pytest -m "not integration"` |
| **RLS integration** (`tests/integration`) | Against a real Postgres built from `supabase/migrations`: cross-user isolation, no self-upgrade of subscriptions, masked BYOK view, signup trigger, Realtime publication | `npx --prefix frontend supabase db start --workdir .` then `pytest -m integration` |
| **Frontend e2e** (`frontend/e2e`, Playwright) | Every public page on desktop and a phone, no sideways scroll at 360/390/430 px, the phone menu, the auth redirect, 404, theme persistence | `cd frontend && npm run test:e2e` |

- **Install:** `pip install -e ".[dev,mcp]"`.
- **Network guard:** a unit test that tries to open a non-loopback connection fails.
- **Coverage floor:** 55%. Raise it as coverage grows.

## Eval harness (M2)

`src/eval/golden_set.jsonl` holds 18 hand-labeled campaign ideas spanning the
domain taxonomy, each with an expected domain tag and a feasibility-score
range. `python -m src.eval.run_eval` runs every idea through
`idea_intake` → `feasibility` → `audience`, judges persona quality with an
LLM (`src/eval/judge.py`, tiered via `PAID_JUDGE_API_KEY` same as other
capabilities), and prints a report:

```
.venv\Scripts\python -m src.eval.run_eval
```

Exits non-zero if the overall score (domain accuracy + feasibility-in-range
rate + average persona quality, equally weighted) falls below 60% — this is
what `.github/workflows/eval.yml` runs on every push/PR, with
`GROQ_API_KEY`/`NEWSAPI_KEY` configured as repo Actions secrets (Reddit
secrets are optional/on hold, same as local `.env`).

## Human-in-the-loop gates + frontend (M3)

Single-tenant, no auth yet (M4 adds that). Setup:

1. Apply the schema (see [Database and Edge Functions](#database-and-edge-functions)):
   `campaigns`, `personas`, `iterations`, `gate_decisions` and the rest.
2. Set in `.env`: `SUPABASE_URL` (same project URL as `TRACK_CLICK_BASE_URL`'s
   host) and `SUPABASE_SERVICE_ROLE_KEY` (Project Settings → API →
   "service_role" secret — server-side only, never expose this one).
3. `cd frontend && npm install && copy .env.example .env`, then fill in
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (same page, "anon
   public" key — safe to expose in the browser; from M4 on, row-level
   security limits it to the logged-in user's own rows).
4. `npm run dev` to run the frontend locally.

Create a campaign from the Dashboard (see "Using the app" below) — it runs
idea → feasibility → audience, then pauses at Gate 1. Approve/Edit/Reject
directly on the campaign's page; the frontend handles resuming the graph
for you (see M5's `resume-campaign` Edge Function). Re-invoking the graph
while a gate is still undecided is a no-op (prints "still awaiting gate N
decision") — this is the checkpoint-and-no-op pattern `campaign-loop.yml`
uses (M5) to poll without erroring. Once Gate 1 is approved, the graph
generates creative,
runs it through the pre-flight persona panel (retrying up to 3 times,
keeping the best-scoring attempt), then pauses again at Gate 2. Approving
Gate 2 triggers real distribution (subject to `DRY_RUN`, same as always).

## Multi-tenancy + BYOK + Tools (M4)

Adds Supabase Auth (email+password) and `user_id`-scoped row-level security
across every tenant table, plus a full 3-tier provider precedence resolved
per logged-in user: **BYOK** (their own key, Settings page, AES-256-GCM
encrypted server-side in a `submit-provider-key` Edge Function) →
**our-paid-if-subscribed** (a `subscriptions` stub flag, toggled by the
operator via `python -m src.admin.set_subscription <email> subscribed` —
this one action has no frontend since it's a billing decision made by you,
not the end user) → **free**
(same `.env` keys as always). The Tools page runs any capability standalone
(dispatches `capability-run.yml` via a `trigger-capability-run` Edge
Function, result shown live via Supabase Realtime). With the schema applied, sign up
two test users in the frontend to confirm RLS actually denies cross-user
reads (not just UI-hidden).

**BYOK keys are stored in Supabase Vault.**
- **How:** the `submit-provider-key` function passes the key to `store_provider_key()`. That function, like `read_provider_key()`, runs as `security definer` and only the service role can call it. `provider_keys` keeps just a Vault pointer and the masked key.
- **Who can read a key:** nobody but the workers, not even with SQL a user can run. Users can only read their masked keys and delete their own rows, which also deletes the secret.
- **Keys saved before the Vault move** were AES-encrypted. They keep working through the legacy decrypt path until `python -m src.admin.migrate_keys_to_vault --apply` moves them; after that, `SETTINGS_ENCRYPTION_KEY` can be retired.

## Feedback loop + autonomy (M5)

Adds `metrics_collector.py` (Bluesky/Reddit engagement + email click-through
via `track-click`) and `feedback_correction.py`, which decides whether to
loop back to another round or stop, enforces tier-based round caps
(free: 3, subscribed/BYOK: 10), and writes a `campaign_summary` closing
artifact. `run_iteration.py` + `campaign-loop.yml` (GitHub Actions) provide
both the hourly reliability sweep (`schedule`, no input) and immediate
per-campaign resumption (`workflow_dispatch`, `campaign_id` input) — the
latter triggered instantly by the `resume-campaign` Edge Function on a gate
decision or "stop campaign" (campaign *creation* instead dispatches
`run_campaign.py` via the separate `create-campaign` Edge Function, added
alongside the multilingual work below). Set `SUPABASE_DB_URL`
(Project Settings → Database → Connection string — this is what lets
LangGraph's Postgres checkpointer survive across separate, ephemeral
GitHub Actions runs), and add the same GitHub Actions secrets already used
by `capability-run.yml` plus `SUPABASE_DB_URL` to the repo's Actions secrets.

## Contextual bandit + memory/RAG + observability (M6)

Adds `tools/bandit.py` — a LinUCB contextual bandit over a fixed 20-arm
catalog (5 image styles × 4 copy tones) driving each round's creative
style/tone selection, and `tools/memory.py` — per-user pgvector embeddings
used for feasibility grounding and a novelty check (retries creative
generation up to 3 times if too similar to this user's own past creative,
per the same best-attempt pattern the pre-flight loop already uses). Schema: `bandit_arms`,
`embeddings` + `pgvector`, and new persona/iteration columns (all in [`supabase/migrations/`](./supabase/migrations/)). The
`Metrics.tsx` frontend page (linked from a campaign's detail view) shows
per-round/per-channel real engagement, the normalized reward, which arm was
used, and a reward-trend chart. LangSmith tracing is optional — set
`LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` in `.env` (LangGraph reads
these automatically, no code change needed).

**Note:** `sentence-transformers` pulls in `torch`, a large download (~1GB+
depending on platform) — if `pip install -e .` times out or drops mid-download
on a slow/flaky connection, just re-run it; pip resumes partial downloads.

## Fine-tuned domain classifier (M7)

Every campaign starts by classifying the idea into one of 12 product domains.
That label is the bandit's domain context, so it decides which past campaigns a
new one learns from. M7 distils that decision from the production LLM
(`gpt-oss-120b` on Groq, the "teacher") into **Qwen2.5-1.5B-Instruct with a LoRA
adapter**, served locally on CPU through llama.cpp.

**Data** (`src/finetune/generate_dataset.py`): the teacher wrote 564 varied
ideas (B2B/B2C, price points, six non-English languages, deliberately
borderline cases) and labelled each one through the real `normalize_idea()`
prompt. Near-duplicates and anything too close to the golden eval set were
removed (cosine on the app's multilingual embeddings), leaving 560 ideas split
417 / 47 / 96. The first model is trained on synthetic data only.

**Training** (`src/finetune/train_lora.ipynb`): Unsloth on a free Colab T4,
LoRA r=16 on all attention and MLP projections, loss on the answer tokens only,
3 epochs. Exported as a 4-bit GGUF (`Q4_K_M`, ~940 MB).

**Results** (`src/finetune/evaluate_finetune.py`, CPU):

| Model | Golden accuracy (human labels, n=18) | Agreement with teacher (held-out, n=96) | Invalid outputs |
|---|---|---|---|
| Teacher: `gpt-oss-120b` via Groq | 83% | 100% (it wrote the labels) | 0 |
| Qwen2.5-1.5B, untuned | 56% | 54% | 3 |
| **Qwen2.5-1.5B + LoRA** | **83%** | **75%** | **0** |

The student matches the teacher on human-labelled ideas at ~0.6–0.8 s per idea
on CPU, with no API call, no per-token cost and no exposure to the free tier's
200k-tokens-per-day limit.

**Honest limits.** Distillation copies the teacher's habits: the teacher never
answered `other` (0 of 47 "other" ideas), so the student can't either, and its
three golden misses are exactly those. Both over-use `ecommerce_retail`, and
`healthcare` has only 13 training examples. Fixing this needs better labels than
the teacher's: human category corrections are the planned source, fed into a
scheduled retrain that only promotes a new model if it scores at least as well.

**Human corrections.** Gate 1 shows the predicted category in a dropdown; if the user changes it, the campaign is updated (the graph re-reads it after the gate, so the bandit uses the corrected context) and the fix is stored in `domain_corrections` as a human-verified training label. The table is part of [`supabase/migrations/`](./supabase/migrations/).

**Weekly retrain** ([`retrain-domain-model.yml`](./.github/workflows/retrain-domain-model.yml), Sundays 03:00 UTC, or run it by hand with *force*). No Groq calls:

1. `python -m src.finetune.retrain prepare`: synthetic train/val plus every human correction (weighted ×3; a correction overrides the teacher's label for the same idea). It skips the week if there are fewer than 30 new corrections since the published model's `training_meta.json`. About 1 in 5 corrections is held back for the gate and never trained on.
2. Train on a free Kaggle T4 ([`src/finetune/kaggle/train_kernel.py`](./src/finetune/kaggle/train_kernel.py), same recipe as the notebook) via a private Kaggle dataset and kernel.
3. `retrain evaluate`: the candidate and the current model are compared on the golden set (human labels), the held-back corrections (human labels) and the held-out synthetic test (teacher agreement, 3-point slack). The candidate is promoted only if it is not worse on any of them.
4. `retrain promote`: upload the GGUF and `training_meta.json` to the private HF repo. The other workflows pick it up on their next run.

**First run (2026-10-21)** was forced, with 0 corrections, so it trained on the same synthetic data as the Colab model. It took 22 minutes, 17 of them on Kaggle. Both models were scored on the same CI runner:

| Model | Golden (human labels) | Held-out (teacher agreement) |
|---|---|---|
| Current (Colab v1) | 78% (14/18) | 72% |
| Candidate (Kaggle) | 83% (15/18) | 78% |

The candidate was promoted. The same v1 file scored 83% / 75% on a Windows laptop: llama.cpp builds can flip a borderline greedy decode, so the gate always scores both models in the same job.

Secrets: `KAGGLE_USERNAME`, `KAGGLE_KEY` (the Kaggle account must be phone-verified for GPU and internet), `SUPABASE_*`, `DOMAIN_MODEL_HF_REPO`, and `HF_WRITE_TOKEN` (a write-scoped HF token; falls back to `HF_TOKEN`).

**In the app** (`src/providers/free/local_domain_classifier.py`): free-tier
campaigns use the local model; BYOK and subscribed users keep their paid LLM.
If the model is missing, can't load, or returns an invalid label, the call falls
back to the LLM, so it can never break a run. `DOMAIN_CLASSIFIER=llm` switches it
off. The GGUF lives in a private Hugging Face model repo
(`DOMAIN_MODEL_HF_REPO` + `HF_TOKEN` secrets) and the workflows cache it between
runs, keyed on the Hugging Face repo's current revision. Locally:

```
pip install -e ".[local-model]" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
# put the GGUF at src/finetune/models/marketingos-domain-q4_k_m.gguf
```

## MCP server (M8)

[`src/mcp_server/server.py`](./src/mcp_server/server.py) exposes the same `capabilities/` functions the graph, the Tools page and CI use. It wraps them, it doesn't reimplement them, so Claude Desktop, Claude Code or any other MCP client gets exactly the app's behaviour.

| Tool | What it does |
|---|---|
| `classify_idea` | Normalizes the idea and picks its category (the fine-tuned M7 model when installed, else the LLM) |
| `score_feasibility` | 0–100 score from live Trends, news and Bluesky/Mastodon signals, plus rationale |
| `generate_personas` | Customer personas grounded in the feasibility signals |
| `generate_creative` | Copy and an image for one persona; the LinUCB bandit picks the style/tone archetype |
| `generate_image` | A single image from the user's image provider |
| `preflight_creative` | Synthetic persona-panel pre-test: predicted engagement and pass/fail |
| `post_bluesky`, `send_campaign_email` | Distribution: **dry runs unless the server runs with `DRY_RUN=false`**, deduplicated per campaign/round |
| `list_campaigns`, `campaign_summary` | Read-only results for `MCP_USER_ID`'s own campaigns |

Tools carry MCP annotations (read-only, or open-world/destructive for the senders), so clients can ask before sending anything.

- **Configuration** comes from the repo's `.env`.
- **`MCP_USER_ID`** (your Supabase user id) is optional. When set, it resolves your BYOK/paid providers and unlocks the campaign tools. Those tools only ever return that user's campaigns: another user's campaign id gets the same "not found" as a missing one, even though the server holds the service-role key.

```
pip install -e ".[mcp]"          # plus ".[local-model]" for the M7 classifier
python -m src.mcp_server.server  # stdio; add --http 8765 for streamable HTTP on 127.0.0.1
```

Claude Code: `claude mcp add marketingos -- <repo>/.venv/Scripts/python.exe -m src.mcp_server.server` (works from any directory; the server loads the repo's `.env` itself).
Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "marketingos": {
      "command": "C:/path/to/repo/.venv/Scripts/python.exe",
      "args": ["-m", "src.mcp_server.server"],
      "env": { "MCP_USER_ID": "<your Supabase user id>", "DRY_RUN": "true" }
    }
  }
}
```

**Implementation notes:**
- Capability code is blocking, so each tool runs in a worker thread with `stdout` redirected to `stderr`, because `stdout` is the stdio wire.
- On Windows, a DLL-backed module (numpy, llama.cpp, torch) first imported from a worker thread deadlocks while the transport's thread is blocked reading stdin. The server therefore imports them on the main thread before it starts serving.

## Multilingual campaigns

Every campaign has a `target_language` (`src/languages.py`, ~15 languages),
chosen from the Dashboard's Create Campaign form — independent of whatever
language the idea itself was typed in. Feasibility rationale, personas, ad
copy, and feedback reasoning are all generated in that language; `image_prompt`
deliberately always stays in English regardless (image models are
English-prompt-optimized — only the visible copy needs to match the target
market). Research signals are localized too: NewsAPI's `language` param and
Google Trends' `hl` both follow `target_language`. The embedding model
(`tools/memory.py`) is multilingual (`paraphrase-multilingual-MiniLM-L12-v2`,
also 384-dim) so retrieval/novelty-check work correctly across languages for
the same user — confirmed live (an English query matched a Spanish embedding
at 0.9 cosine similarity). (`campaigns.target_language`, in [`supabase/migrations/`](./supabase/migrations/).)

The frontend's own UI chrome is separately localizable via `react-i18next`
— a language switcher in the nav bar, independent of any campaign's
`target_language`. Ships with 5 locales (English/Spanish/French/Hindi/
Portuguese, `frontend/src/i18n/locales/`); add another by dropping in a new
locale JSON with the same keys. The public marketing page (`/`) is
deliberately English-only; localization covers the logged-in app.

## Deploying the frontend

The frontend is a static Vite build, so any static host works. Vercel is the
default (`frontend/vercel.json`); Netlify is covered by `frontend/public/_redirects`.
Both send every route to `index.html`, so deep links like `/campaigns/<id>`
survive a page reload.

1. **Redeploy the four browser-facing Edge Functions** (`create-campaign`,
   `resume-campaign`, `submit-provider-key`, `trigger-capability-run`) from
   `supabase/functions/` (the Supabase deploy workflow does this once its secrets are set). They answer the browser's CORS preflight; the
   earlier versions rejected it with a 401, which blocks every call made from
   the website.
2. **Import the repo on Vercel** with **Root Directory = `frontend`**. The
   framework preset is Vite; build and output settings come from `vercel.json`.
3. **Set the environment variables** in the Vercel project (Production and
   Preview): `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`. Use the anon key
   only, never the service-role key.
4. **Tell Supabase about the new origin** (Authentication → URL Configuration):
   - **Site URL**: the production URL, e.g. `https://marketingos.vercel.app`.
     Email confirmation links land here.
   - **Redirect URLs**: add `https://<your-domain>/**` (and keep
     `http://localhost:5173/**` for local development). Google and GitHub
     sign-in return to `/login` on whichever origin started them.
5. **Google / GitHub sign-in (optional)**: the provider callback stays the
   Supabase URL (`https://<project-ref>.supabase.co/auth/v1/callback`). For
   Google's consent screen, use the deployed `/privacy` and `/terms` pages.

Smoke check after deploying: open `/`, `/about` and a made-up URL (it should
show the 404 page, not a host error), sign in, create a campaign from the
Dashboard, and confirm no CORS errors appear in the browser console.
