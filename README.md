# Agentic Ad Campaign Platform

Closed-loop, agentic system that takes an ad campaign from idea → feasibility
scoring → audience generation → creative production → multi-channel launch →
metrics-driven feedback → iterative correction → stop, entirely on free-tier
infrastructure. Full design and milestone plan: [`DESIGN.md`](./DESIGN.md).

**Status:** M1 (provider abstraction, capabilities layer, single-shot
pipeline) built; M2 (eval harness) built.

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
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | reddit.com/prefs/apps (create a "script" app) |
| `REDDIT_USERNAME` / `REDDIT_PASSWORD` | your Reddit test account |
| `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` | bsky.app Settings → App Passwords |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `RESEND_TEST_TO_EMAIL` | resend.com |

Optional paid keys (`PAID_LLM_API_KEY`, `PAID_IMAGE_API_KEY` — both OpenAI)
upgrade the LLM/image-gen tier; leave blank to stay on the free tier.
`FORCE_FREE_TIER=true` forces free providers even if paid keys are set.

### Distribution safety

`DRY_RUN=true` (the default) makes every `capabilities/distribution.py`
function log what it *would* send and return a synthetic result — no real
Bluesky/Reddit/email calls. Set `DRY_RUN=false` to actually send. Every
distribution call also takes a `campaign_id`/`round_id`, deduped against a
local `.local_dedup_store.json` (gitignored) so the same campaign/round/
channel is never sent twice — a placeholder for the Supabase
`distribution_dedup` table that lands in M3.

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

## Run

Full pipeline, one pass, no loop:

```
.venv\Scripts\python -m src.graph.build_graph "A subscription box for artisanal hot sauce"
```

Each capability standalone via the CLI:

```
.venv\Scripts\python -m src.cli feasibility "A subscription box for artisanal hot sauce"
.venv\Scripts\python -m src.cli image "a jar of hot sauce on a rustic wooden table"
.venv\Scripts\python -m src.cli personas "A subscription box for artisanal hot sauce"
.venv\Scripts\python -m src.cli creative "A subscription box for artisanal hot sauce"
.venv\Scripts\python -m src.cli post-bluesky "hello from the ad campaign agent" --campaign-id demo --round-id 1
.venv\Scripts\python -m src.cli post-reddit test "test post" "test body" --campaign-id demo --round-id 1
.venv\Scripts\python -m src.cli send-email "test subject" "test body" --cta-url "https://example.com" --campaign-id demo --round-id 1
```

All three distribution commands default to `DRY_RUN=true` — set
`DRY_RUN=false` in `.env` when you're ready to confirm a real send.

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
what `.github/workflows/eval.yml` runs on every push/PR once this repo has a
GitHub remote with `GROQ_API_KEY`/`NEWSAPI_KEY`/`REDDIT_*` configured as
Actions secrets.
