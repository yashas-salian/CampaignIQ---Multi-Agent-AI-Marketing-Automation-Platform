# MarketingOS — Handoff / Continuation Guide

> Written 2026-10-19 so work can continue on a different laptop and a different
> Claude account. Give this file to the new Claude session first, then
> `DESIGN.md` (full spec, source of truth) and `README.md` (setup per
> milestone). This file summarizes those two and adds the current state that
> isn't written down anywhere else.

---

## 1. What this project is

An **agentic ad-campaign platform** that takes a campaign through this loop:
**idea → feasibility score → audience personas → (human gate 1) → creative
(image + copy) → pre-flight persona panel → (human gate 2) → real distribution
(Bluesky + email) → metrics → feedback / bandit update → next round … → stop.**
Everything runs on free-tier infrastructure. It's a portfolio piece aimed at
YC-calibre AI/ML roles, so it favours real integrations, a real optimization
loop (LinUCB contextual bandit), an eval harness and real multi-tenancy.

**Stack**
| Layer | Tech |
|---|---|
| Agent logic | Python 3.12, LangGraph 0.2.x, Pydantic v2 |
| LLM / image | Groq (free) / OpenAI (paid or BYOK); Pollinations (free) / OpenAI `gpt-image-2` (paid) |
| Data, auth, realtime | Supabase (Postgres + RLS + Auth + Realtime + pgvector) |
| Backend for secrets/dispatch | 5 Supabase Edge Functions (Deno/TS) |
| Workers / scheduling | GitHub Actions (`campaign-loop.yml`, `capability-run.yml`, `eval.yml`) |
| Frontend | Vite + React 19 + TypeScript + Tailwind v4 + react-router 7 + react-i18next |
| Embeddings | `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`, 384-dim), runs locally |
| Observability | LangSmith (optional) |

**Scope:** M1–M6 is the core to finish. M7 (LoRA fine-tune), M8 (MCP server)
and M9 (stretch) are deliberately **out of scope** until M1–M6 is polished.

**Git remote:** `https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform` (branch `main`).

---

## 2. Status of the work

| Milestone | What it covers | Status |
|---|---|---|
| M1 | Provider abstraction (3-tier registry), capabilities layer, tools (trends, news, Bluesky, Mastodon, Resend, Pollinations, dedup, track-click), linear graph | ✅ Done, verified live |
| M2 | Eval harness: 18-idea golden set, LLM-as-judge, `eval.yml` CI | ✅ Done, verified live. First run: domain 94%, feasibility in range 39% (Trends rate-limiting pulled this down), persona 88%, overall 74%, PASS at a 60% threshold |
| M3 | Supabase schema, human gates (LangGraph `interrupt()` / `Command(resume=)`), pre-flight panel, first frontend | ✅ Done, verified live |
| M4 | Supabase Auth + RLS on all tenant tables, BYOK (AES-256-GCM, Deno encrypts → Python decrypts), subscription stub, Settings + Tools pages | ✅ Done, verified live (RLS denies cross-user reads at the Postgres layer; Tools page works end to end through GitHub Actions) |
| Templates (extra) | Per-user image/email templates, opted into per campaign. Free tier: corner-watermark composite. Paid/BYOK tier: OpenAI outpainting | ✅ Done. ⚠️ The OpenAI `images.edit()` outpainting call has **never been verified live** (no paid key). This is accepted; it's not a blocker |
| M5 | Metrics collector, feedback/correction, tier round caps (free 3 / paid 10), `campaign_summary`, `run_iteration.py`, `campaign-loop.yml` (hourly cron + dispatch), `resume-campaign` + `create-campaign` Edge Functions, Postgres checkpointer | ✅ Committed (`82425c0 M5 done`). README says it's live-verified |
| M6 | LinUCB bandit (20 arms = 5 image styles × 4 copy tones), per-user pgvector memory + novelty check, Metrics page, LangSmith, `docs/architecture.md` | ✅ Committed and pushed (inside `323a530`). README says it's live-verified |
| Multilingual (extra) | `target_language` per campaign (~15 languages), 5 UI locales | ✅ Done |
| CLI removal | `src/cli.py` deleted. Everything is done in the frontend; the operator billing action is `src/admin/set_subscription.py` | ✅ Committed (`323a530`) |
| **Frontend redesign** | New public `Landing` page (video scrub, loop explainer), light/dark `ThemeContext`, `shell.module.css`, Fraunces fonts, restyled all pages | 🟡 **In progress and uncommitted.** Typecheck passes |
| Reddit | Feasibility signal + distribution channel | ⏸ On hold (no API creds). The code is kept, behind `ENABLE_REDDIT=false` |

**Progress on the M1–M6 core:** all six milestones are built. What's left is
polish: commit the frontend redesign, record the demo video/GIF and finish the
README portfolio section.

---

## 3. What's in git and what isn't (checked 2026-10-19)

**In git and pushed:** all backend code (M1–M6), the SQL schemas, the Edge
Functions, the workflows, the docs, and the frontend up to the M6 pages.
Last pushed commit: `323a530 Removes CLI and shifting everything to FE`.
Local `main` was level with `origin/main` at that point.

**Not in git yet. The user is pushing these before switching laptops:**

```
 M frontend/src/App.tsx            (routes: "/" → Landing, theme toggle, new top bar)
 M frontend/src/index.css
 M frontend/src/pages/{CampaignDetail,Dashboard,Login,Metrics,Settings,Tools}.tsx
?? frontend/src/pages/Landing.tsx + Landing.module.css
?? frontend/src/lib/ThemeContext.tsx
?? frontend/src/styles/shell.module.css
?? frontend/public/fonts/fraunces-var.ttf, fraunces-italic-var.ttf
?? frontend/public/pixis.ai.mp4   (~29 MB, under GitHub's 100 MB limit)
?? HANDOFF.md                     (this file)
```

> **New Claude: check first.** Run `git log --oneline -3` and `git status`.
> If the latest commit is still `323a530` and `frontend/src/pages/Landing.tsx`
> doesn't exist, the redesign push didn't happen. Tell the user before doing
> anything else.

**Never in git (by design, gitignored). Transfer by hand:**

Copy these files securely (password manager, encrypted USB; not chat or
email):
- `MarketingOS/.env` (26 keys, listed in §5.3)
- `MarketingOS/frontend/.env` (`VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`)

The Supabase project, the Edge Functions and the GitHub Actions secrets live
in the cloud and are **already set up**. You don't redeploy them on the new
laptop; you only need the two `.env` files.

Files you don't need to copy (local, regenerated or gitignored):
`.venv/`, `frontend/node_modules/`, `frontend/dist/`,
`.langgraph_checkpoints.sqlite` (old M3 local checkpointer),
`.local_dedup_store.json`.

---

## 4. Repo map

```
MarketingOS/
  DESIGN.md              ← full spec + "Implementation specifics" (source of truth)
  README.md              ← setup per milestone, Edge Function table
  docs/architecture.md   ← mermaid flow + "why this isn't an LLM wrapper"
  pyproject.toml         ← Python deps (pip install -e .)
  .env.example           ← every backend env var, documented
  src/
    constants.py         ← METRICS_WAIT_HOURS, round caps, retry caps, active_channels()
    languages.py, llm_json.py
    providers/           ← base.py, registry.py (BYOK → paid-if-subscribed → free), crypto.py (AES-GCM), free/, paid/
    capabilities/        ← idea_intake, feasibility, audience, creative, preflight, distribution, metrics, feedback_correction
    tools/               ← trends, news, bluesky_client, mastodon_client, reddit_client, resend_client,
                           image_gen, image_compositing, dedup_store, track_click, bandit (LinUCB), memory (pgvector)
    graph/               ← state.py, build_graph.py, run_campaign.py, nodes/ (one thin wrapper per step)
    scheduler/           ← run_iteration.py (cron sweep / --campaign-id), run_capability.py (Tools page)
    admin/set_subscription.py  ← operator-only tier toggle
    db/                  ← supabase_client.py + schema*.sql
    eval/                ← golden_set.jsonl, judge.py, run_eval.py
  supabase_setup/
    sql/click_log.sql
    functions/           ← track-click, submit-provider-key, trigger-capability-run, resume-campaign, create-campaign
  frontend/              ← Vite SPA: pages/ Landing, Login, Dashboard, CampaignDetail, Metrics, Tools, Settings
  .github/workflows/     ← campaign-loop.yml, capability-run.yml, eval.yml
```

How a request flows: the frontend calls an Edge Function, which runs
`workflow_dispatch` on a GitHub Actions workflow. That workflow runs the
Python worker, which writes to Supabase, and the frontend picks the change up
over Realtime. The LangGraph state is checkpointed in Supabase Postgres
(`SUPABASE_DB_URL`), so separate, short-lived Actions runs can pause at a
gate and resume later.

---

## 5. Prerequisites on the new laptop

### 5.1 Software
| Tool | Version used | Notes |
|---|---|---|
| **Python** | 3.12.x (3.12.10 used) | `>=3.11` is required. On Windows install with `winget install Python.Python.3.12`. The Microsoft Store `python` stub can shadow it, so **always call the venv's python by full path** (`.venv\Scripts\python.exe`) |
| **Node.js** | 24.x (24.16.0 used) | Must be recent enough for Vite 8 and TypeScript 6 |
| **npm** | 11.x (11.13.0 used) | |
| **Git** | any | |
| Disk / network | ~2–3 GB free | `sentence-transformers` pulls in **torch** (~1 GB+). If `pip install` drops partway, just run it again |
| Supabase CLI | *optional* | Only needed to redeploy Edge Functions from the terminal. Until now they were pasted into the Dashboard |

**Windows-only gotcha:** if Smart App Control is on, it blocks pandas 3.x
native binaries. `pandas==2.2.2` is pinned in `pyproject.toml` for this
reason. Don't unpin it.

### 5.2 Python dependencies (`pyproject.toml`)
```
langgraph>=0.2,<0.3            (0.2.76 installed)
langgraph-checkpoint-sqlite>=2,<3
langgraph-checkpoint-postgres>=2,<3
psycopg[binary]>=3.1,<4
pydantic>=2,<3   python-dotenv   requests
groq>=0.11,<1    openai>=1.40,<2
pytrends>=4.9,<5 pandas==2.2.2   praw>=7.7,<8
atproto>=0.0.55  (0.0.69 installed)   resend>=2.4,<3
supabase>=2.9,<3 (2.31.0 installed)
cryptography>=42,<45   Pillow>=10,<12
sentence-transformers>=3,<4 (3.4.1 installed; pulls torch)
```

### 5.3 Frontend dependencies (`frontend/package.json`)
`@supabase/supabase-js ^2.112`, `react`/`react-dom ^19.2`,
`react-router-dom ^7.18`, `i18next ^26` + `react-i18next ^17`,
`tailwindcss`/`@tailwindcss/vite ^4.3`. Dev dependencies: `vite ^8.2`,
`@vitejs/plugin-react ^6`, `typescript ~6.0`, `oxlint`.

### 5.4 Accounts and keys (`.env`)
| Var | Required? | Source |
|---|---|---|
| `GROQ_API_KEY` | ✅ | console.groq.com |
| `NEWSAPI_KEY` | ✅ | newsapi.org (100 req/day) |
| `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD` | ✅ | bsky.app → Settings → App Passwords (dedicated test account) |
| `MASTODON_INSTANCE_URL`, `MASTODON_ACCESS_TOKEN` | optional (token makes search actually return results) | instance → Settings → Development |
| `RESEND_API_KEY`, `RESEND_FROM_EMAIL` (`onboarding@resend.dev`), `RESEND_TEST_TO_EMAIL` | ✅ | resend.com |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Supabase → Project Settings → API (project ref `jpytagvsjovzylyfssfm`) |
| `SUPABASE_DB_URL` | ✅ (M5+) | Supabase → Database → Connection string (needs the DB password) |
| `SETTINGS_ENCRYPTION_KEY` | ✅ (M4+) | base64 32-byte key. **Must match** the `submit-provider-key` Edge Function secret, so reuse the existing value and don't generate a new one |
| `TRACK_CLICK_BASE_URL` | ✅ for email CTA tracking | `https://<ref>.supabase.co/functions/v1/track-click` |
| `DRY_RUN` | ✅ | ⚠️ It's **`false` in the current local `.env`**, which means real posts and emails get sent. Set it to `true` while testing |
| `ENABLE_REDDIT` | keep `false` | `REDDIT_*` can stay blank |
| `FORCE_FREE_TIER` | `false` | `true` forces the free providers |
| `PAID_LLM_API_KEY`, `PAID_IMAGE_API_KEY`, `PAID_JUDGE_API_KEY` | optional | OpenAI |
| `METRICS_WAIT_HOURS` | optional (default 6) | Set something like `0.05` for fast local demos |
| `LANGCHAIN_TRACING_V2`, `LANGCHAIN_API_KEY`, `LANGCHAIN_PROJECT` | optional | LangSmith |

`frontend/.env` holds `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (the
anon key, never the service role key).

**Already in the cloud (no action needed unless something's broken):**
- Edge Function secrets: `SETTINGS_ENCRYPTION_KEY`, plus `GITHUB_REPO` and
  `GITHUB_PAT` (PAT needs `actions:write`) for trigger-capability-run,
  resume-campaign and create-campaign. `track-click` has **JWT verification
  OFF**; the others have it ON.
- GitHub Actions repo secrets: all the keys above, plus `SUPABASE_DB_URL` and
  `DRY_RUN`.
- SQL already applied, in this order: `click_log.sql` → `schema.sql` →
  `schema_m4.sql` → `schema_m5.sql` → `schema_templates.sql` →
  `schema_m6.sql` → `schema_i18n.sql`.

---

## 6. Setup and smoke tests on the new laptop (do these before writing new code)

```powershell
git clone https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform MarketingOS
cd MarketingOS
# put the copied .env here and frontend\.env in frontend\
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -U pip
.venv\Scripts\python.exe -m pip install -e .
cd frontend; npm install; cd ..
```

Set **`DRY_RUN=true`** in `.env` before running anything below.

| # | Test | Command / action | Expected outcome |
|---|---|---|---|
| 1 | Python imports | `.venv\Scripts\python.exe -c "import src.graph.build_graph, src.tools.bandit, src.tools.memory; print('ok')"` | Prints `ok`. The first import of `memory` may download the embedding model (~470 MB) |
| 2 | Frontend typecheck and build | `cd frontend; npm run build` | `tsc -b` passes and Vite writes `dist/` with no errors |
| 3 | Lint (optional) | `npm run lint` | No errors from oxlint |
| 4 | Frontend runs | `npm run dev` → http://localhost:5173 | The Landing page loads (video, loop steps, theme toggle). `/login` lets you sign in |
| 5 | Eval harness | `.venv\Scripts\python.exe -m src.eval.run_eval` | Prints a report for 18 ideas and exits 0 when overall is ≥ 60%. Expect roughly domain 90%+ and persona 85%+. Feasibility-in-range is noisy because Google Trends rate-limits; the run falls back to a neutral signal and flags it as `rate_limited` instead of crashing |
| 6 | Tier toggle | `.venv\Scripts\python.exe -m src.admin.set_subscription <test-email> subscribed` | Finds the user and flips their `subscriptions.status` |
| 7 | Full campaign through the UI | Dashboard → Create campaign (idea + language) | `create-campaign` dispatches `campaign-loop.yml` in GitHub Actions. The campaign appears with feasibility and personas, then status `awaiting_gate_1` |
| 8 | Gate 1 | Approve on CampaignDetail | `resume-campaign` runs. A new creative appears (bandit arm, image, copy, pre-flight score), then status `awaiting_gate_2` |
| 9 | Gate 2 | Approve | Distribution runs. With the **Actions** secret `DRY_RUN=true`, the iteration shows `DRY_RUN: would …` values. Status becomes `awaiting_metrics` |
| 10 | Loop | Wait `METRICS_WAIT_HOURS` (hourly cron) or dispatch `campaign-loop.yml` manually with `campaign_id` | Metrics are collected, the bandit reward is updated, and the next round runs. A free-tier campaign stops after 3 rounds with a `campaign_summary` |
| 11 | Metrics page | `/campaigns/:id/metrics` | Per-round and per-channel counts, normalized reward, arm used, reward-trend chart |
| 12 | Tools page | Run feasibility / personas / image | A `capability_runs` row goes pending → completed and the result appears live through Realtime |
| 13 | Settings / BYOK | Save a key | Only a masked value (last 4 characters) is ever shown |
| 14 | Local worker (optional) | `.venv\Scripts\python.exe -m src.scheduler.run_iteration` | Sweeps due campaigns. It no-ops ("still awaiting gate N") on ones parked at a gate |

If 1–5 pass, the local environment is good. Steps 7–13 also exercise the cloud
side (Supabase, Edge Functions, GitHub Actions secrets).

---

## 7. Next steps (in order)

1. **Confirm the redesign push landed** (see the check in §3). Make sure the
   `frontend/.env` comment still describes RLS as off, and correct it, since
   RLS has been on since M4.
2. **Finish and QA the frontend redesign:**
   - Check every page in light and dark theme and at mobile width (Landing,
     Login, Dashboard, CampaignDetail, Metrics, Tools, Settings).
   - The Landing page is public at `/`. Check its CTAs route to `/login` and
     `/dashboard`, and that a logged-in user sees sensible navigation (the
     TopBar only renders when there's a session).
   - Make sure the new Landing copy is covered by i18n keys, or decide it
     stays English-only.
   - Check the performance cost of the 29 MB `pixis.ai.mp4`: compress it or
     lazy-load it, and add a poster image.
   - `npm run build` and `npm run lint` should both be clean.
3. **Deploy the frontend** as a static build on Vercel or Netlify. Set the
   `VITE_*` env vars and add an SPA rewrite so all routes serve `index.html`.
   Add the deployed origin to Supabase Auth → URL configuration.
4. **Portfolio polish (the remaining M6 deliverable in DESIGN.md):**
   - Record a demo video/GIF centred on the Metrics page with a short
     multi-round campaign (`METRICS_WAIT_HOURS` set low).
   - README portfolio section: problem framing, architecture diagram, what
     makes the loop real and what makes it learn, the business model, and
     documented limitations (shared distribution accounts, stubbed billing,
     unlocked bandit writes, Reddit on hold).
5. **Optional verifications** (known gaps, not blockers):
   - Realtime events respect RLS for every subscribed table (user B never
     receives events for user A's rows).
   - The cross-user bandit check from the M6 verification list:
     same-domain transfer happens, cross-domain transfer doesn't.
   - Outpainting, only once a paid OpenAI key with `gpt-image-2` exists.
6. **Only after all of the above:** M7 (LoRA fine-tune on accumulated data
   via Unsloth on Colab), then M8 (MCP server wrapping `capabilities/`). See
   DESIGN.md.

**Definition of done for the current phase:** a fresh clone builds and runs
on the new laptop, the redesigned frontend is deployed at a public URL, a
full 3-round free-tier campaign completes end to end with a populated
`campaign_summary` and Metrics chart, the eval workflow is green on `main`,
and the README has the demo video and portfolio write-up.

---

## 8. Rules and conventions for the next Claude session

- **Read `DESIGN.md` fresh at the start**, because it gets edited outside
  Claude. Where it and the code disagree, the later "post-M6" sections of
  DESIGN.md win. For example, the CLI no longer exists.
- **No git writes** (add, commit, push) unless the user explicitly asks in
  that moment. Report what changed and let the user commit.
- After each phase, **summarize the work in the chat reply** and give the
  M1–M6 % complete (milestones weighted equally).
- When the user asks "do you think we should X / suggest…", give a
  recommendation only. Don't implement it until they approve.
- All agent and AI logic stays in **Python**. TypeScript is limited to the
  frontend and the small Edge Functions.
- **Never let one flaky external API crash a run.** Retry where the failure
  is known (pytrends), otherwise catch and degrade to a neutral signal
  (`_safe_signal()` in `feasibility.py`).
- LangGraph node names must not collide with state keys (for example, a node
  can't be named `feasibility`).
- Don't name a local folder after a pip package (`supabase/` was renamed to
  `supabase_setup/` for this reason).
- `providers/registry.py` imports `db.supabase_client` **lazily** inside
  functions to avoid a circular import. Keep it that way.
- Templates **never replace** generation; they're combined with fresh output
  (`{{COPY}}` placeholder for email, overlay or outpaint for images).
- Every categorical field in the bandit context (age bracket, income tier,
  domain) is a Pydantic `Literal`, never free text.
- Free-tier round cap is 3 and paid/BYOK is 10. `maxDurationMinutes` is
  derived as `rounds × METRICS_WAIT_HOURS × 60 × 1.5`, never hand-set.

---

## 9. Starter prompt for the new Claude session

Paste this as the first message in Claude Code, run from inside the cloned
`MarketingOS` folder:

```
I'm continuing an existing project, MarketingOS (an agentic ad-campaign
platform: Python/LangGraph + Supabase + Vite/React + GitHub Actions). I've
moved to a new laptop and a new Claude account, so you have no prior context.

Read these files first, in this order, before doing anything else:
1. HANDOFF.md: current status, what's in git, prerequisites, smoke tests,
   next steps, and the rules you must follow. Treat its §8 rules as standing
   instructions.
2. DESIGN.md: the full spec and source of truth. The later sections ("CLI
   removed…", "RAG type note") override earlier ones.
3. README.md and docs/architecture.md: setup per milestone and the
   architecture.

Then:
- Run `git log --oneline -3` and `git status` and confirm the frontend
  redesign commit (Landing.tsx, ThemeContext.tsx, styles/) is present, as
  described in HANDOFF.md §3.
- Check my machine against HANDOFF.md §5 (Python 3.12, Node 24, npm, .env
  and frontend/.env present, DRY_RUN=true). Tell me what's missing. Don't
  install anything without asking.
- Walk me through the HANDOFF.md §6 smoke tests one at a time, and tell me
  whether each result matches the expected outcome.

Don't write any new feature code until the smoke tests pass and I confirm the
next step from HANDOFF.md §7. Never run git add/commit/push in this repo; I
do that myself. After each phase, summarize what was done here in the chat.
Also save the key project context and these rules to your memory so future
sessions keep them.
```
