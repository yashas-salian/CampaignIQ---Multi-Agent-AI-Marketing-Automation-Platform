# Agentic Ad Campaign Platform

Closed-loop, agentic system that takes an ad campaign from idea → feasibility
scoring → audience generation → creative production → multi-channel launch →
metrics-driven feedback → iterative correction → stop, entirely on free-tier
infrastructure. Full design and milestone plan: [`DESIGN.md`](./DESIGN.md).

**Status:** M1–M6 (the full "must-finish core" per [`DESIGN.md`](./DESIGN.md))
built and live-verified: provider abstraction, eval harness, human-in-the-loop
gates + pre-flight panel, multi-tenancy + BYOK + Tools page, the metrics →
feedback → autonomy loop, and a contextual bandit + per-user memory/RAG.
M7–M9 (fine-tuning, MCP server, stretch) are explicitly out of scope for now.
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
distribution call also takes a `campaign_id`/`round_id`, deduped against a
local `.local_dedup_store.json` (gitignored) so the same campaign/round/
channel is never sent twice.

### `track-click` (email link tracking)

Outgoing emails route their CTA link through a Supabase Edge Function so
click data doesn't depend on Resend's own tracking. This is Supabase
infrastructure pulled forward from M3 — a full Supabase project with
auth/RLS/campaigns tables isn't set up until then, just this one function:

1. Create a free project at supabase.com.
2. In the SQL Editor, run [`supabase_setup/sql/click_log.sql`](./supabase_setup/sql/click_log.sql).
3. In Edge Functions, create a new function named `track-click`, paste in
   [`supabase_setup/functions/track-click/index.ts`](./supabase_setup/functions/track-click/index.ts), and deploy.
4. Set `TRACK_CLICK_BASE_URL` in `.env` to
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

All five are Supabase Dashboard → Edge Functions → paste the file → Deploy
(keep "Enforce JWT Verification" ON for all except `track-click`, which
needs it OFF since email clients follow the link unauthenticated):

| Function | Source | Needs |
|---|---|---|
| `track-click` | `supabase_setup/functions/track-click/index.ts` | — |
| `submit-provider-key` | `supabase_setup/functions/submit-provider-key/index.ts` | `SETTINGS_ENCRYPTION_KEY` secret |
| `trigger-capability-run` | `supabase_setup/functions/trigger-capability-run/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |
| `resume-campaign` | `supabase_setup/functions/resume-campaign/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |
| `create-campaign` | `supabase_setup/functions/create-campaign/index.ts` | `GITHUB_REPO`, `GITHUB_PAT` secrets |

`GITHUB_REPO`/`GITHUB_PAT` are shared across the last three (same repo, same
PAT, only set once). The GitHub Actions side needs every key in `.env`
mirrored as a repo secret (Settings → Secrets and variables → Actions) —
`campaign-loop.yml` and `capability-run.yml` both list exactly which ones
in their `env:` blocks.

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

1. In the Supabase SQL Editor (same project as `track-click`), run
   [`src/db/schema.sql`](./src/db/schema.sql) — creates `campaigns`,
   `personas`, `iterations`, `gate_decisions`.
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
Function, result shown live via Supabase Realtime). Run
[`src/db/schema_m4.sql`](./src/db/schema_m4.sql) after `schema.sql`, sign up
two test users in the frontend to confirm RLS actually denies cross-user
reads (not just UI-hidden), and set `SETTINGS_ENCRYPTION_KEY` (generate with
`python -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"`)
in both `.env` and the Edge Function's own secrets.

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
alongside the multilingual work below). Run
[`src/db/schema_m5.sql`](./src/db/schema_m5.sql), set `SUPABASE_DB_URL`
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
per the same best-attempt pattern the pre-flight loop already uses). Run
[`src/db/schema_m6.sql`](./src/db/schema_m6.sql) (adds `bandit_arms`,
`embeddings` + `pgvector`, and new persona/iteration columns). The
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

**Human corrections.** Gate 1 shows the predicted category in a dropdown; if the user changes it, the campaign is updated (the graph re-reads it after the gate, so the bandit uses the corrected context) and the fix is stored in `domain_corrections` as a human-verified training label. Run [`src/db/schema_m7.sql`](./src/db/schema_m7.sql) once to create that table.

**In the app** (`src/providers/free/local_domain_classifier.py`): free-tier
campaigns use the local model; BYOK and subscribed users keep their paid LLM.
If the model is missing, can't load, or returns an invalid label, the call falls
back to the LLM, so it can never break a run. `DOMAIN_CLASSIFIER=llm` switches it
off. The GGUF lives in a private Hugging Face model repo
(`DOMAIN_MODEL_HF_REPO` + `HF_TOKEN` secrets) and the workflows cache it between
runs, keyed on `src/finetune/MODEL_VERSION`. Locally:

```
pip install -e ".[local-model]" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
# put the GGUF at src/finetune/models/marketingos-domain-q4_k_m.gguf
```

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
at 0.9 cosine similarity). Run [`src/db/schema_i18n.sql`](./src/db/schema_i18n.sql)
(adds `campaigns.target_language`).

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
   `supabase_setup/functions/`. They answer the browser's CORS preflight; the
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
