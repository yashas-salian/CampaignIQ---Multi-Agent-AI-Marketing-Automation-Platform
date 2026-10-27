# CampaignIQ

**A multi-agent AI marketing platform that takes an ad campaign from an idea to measured results, with people approving every step that matters.**

You describe a product and who it's for. CampaignIQ:
1. checks whether the campaign should run at all;
2. writes customer personas;
3. designs the ad around a photo of your real product;
4. stress-tests the ad before anyone sees it;
5. posts it to Bluesky, Mastodon and Reddit and emails your own subscribers;
6. measures what happened, learns, and runs a better round.

Two human gates decide what goes out, and every decision is explained. It runs entirely on free tiers.

![A campaign at Gate 2: the finished ad, its compliance check and the persona panel's reactions](docs/screenshots/gate-2.png)

| Dashboard | Playbooks | Our AI model |
|---|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Playbooks](docs/screenshots/playbooks.png) | ![Model card](docs/screenshots/model-card.png) |

## What it does

- **Decides before it spends.** A decision engine weighs demand, momentum, purchase intent, competition and track record, with each source shown, and recommends launch, test small, wait or kill. Prohibited products and broken links are blocked outright. → [docs/DECISION_ENGINE.md](docs/DECISION_ENGINE.md)
- **Ads built around your real product.** The product photo is cut out and set into one of 34 layout templates drawn from a study of 128 real ads. The AI never repaints your product. → [docs/AD_TEMPLATES.md](docs/AD_TEMPLATES.md)
- **Learns what works.** A contextual bandit picks each round's style and tone from real engagement. A fine-tuned classifier (Qwen2.5-1.5B + LoRA, retrained weekly on human corrections) labels every idea's market.
- **Crash-tests every ad.** Rule checks for invented testimonials, false urgency and claims the brand never made, plus eight simulated reactions, before Gate 2. → [docs/CRASH_TEST.md](docs/CRASH_TEST.md)
- **Emails your own customers, legally.** Each brand connects its own Resend account. Contacts come from a CSV import with consent records, a sign-up form with double opt-in, or the API. Each round emails the next batch of the audience, once per person, with unsubscribe and a safety pause. → [docs/EMAIL_ENGINE.md](docs/EMAIL_ENGINE.md)
- **Proves impact.** A randomized holdout says whether the campaign caused the extra sign-ups, with a confidence interval, or says plainly that it can't tell yet. → [docs/PROOF_OF_IMPACT.md](docs/PROOF_OF_IMPACT.md)
- **Remembers why.** Brand memory keeps the reasons behind your team's decisions and uses them, carefully, in future campaigns. → [docs/BRAND_MEMORY.md](docs/BRAND_MEMORY.md)
- **Watches the market.** Competitor moves from approved public sources, and a fatigue check that notices when an ad is wearing out. → [docs/COMPETITOR_INTELLIGENCE.md](docs/COMPETITOR_INTELLIGENCE.md), [docs/CREATIVE_FATIGUE.md](docs/CREATIVE_FATIGUE.md)
- **Stops itself when it's unsafe.** A live campaign pauses the moment its offer ends, its link breaks, its copy breaks a rule or bad news breaks. → [docs/CIRCUIT_BREAKER.md](docs/CIRCUIT_BREAKER.md)
- **Built for teams.** Organisations and roles, multi-approver gates with deadlines, notifications to the people who must act (in the app, by email, on Slack), comments, an audit log, a public REST API with webhooks, and an MCP server.

## How it works

```
idea ─▶ intake ─▶ feasibility ─▶ personas ─▶ decision ─▶ [Gate 1: a person approves]
                                                                  │
   ┌──────────────────────────────────────────────────────────────┘
   ▼
creative (bandit picks style/tone) ─▶ novelty + persona panel ─▶ crash test ─▶ [Gate 2: a person approves]
   ▲                                                                                     │
   │                                                                                     ▼
feedback (stop or another round) ◀── metrics (engagement, clicks, conversions) ◀── distribution (social + email)
```

| Layer | What runs it |
|---|---|
| Agents and the campaign graph | Python, LangGraph (checkpointed in Postgres) |
| Workers | GitHub Actions: the hourly sweep and per-campaign runs |
| Database, auth, storage, secrets | Supabase: Postgres with row-level security, Vault, Edge Functions (Deno) |
| Web app | React 19, Vite, TypeScript, i18n in 5 languages |
| AI | Groq (`gpt-oss-120b`) with Cerebras, OpenRouter and Gemini fallbacks; FLUX for scene backgrounds; a local fine-tuned classifier; multilingual embeddings in pgvector |
| Channels | Bluesky, Mastodon, Reddit (optional), email through each brand's own Resend account |

More: [docs/architecture.md](docs/architecture.md), and the developer reference [docs/REFERENCE.md](docs/REFERENCE.md).

## Getting started

### What you need

- Python 3.11+ (3.12 is what CI uses) and Node.js 24.
- Docker Desktop, for the local database.
- Free accounts:
  - [Groq](https://console.groq.com) (the LLM);
  - [NewsAPI](https://newsapi.org) (feasibility signals);
  - a Bluesky app password (posting and signals);
  - [Resend](https://resend.com) (the app's own notification email).
- Optional:
  - Mastodon;
  - Cloudflare or Hugging Face for FLUX images;
  - Stripe test mode;
  - Langfuse and Sentry;
  - more LLM fallbacks.

  See [docs/REFERENCE.md](docs/REFERENCE.md#environment-and-keys).

### 1. Backend

```bash
git clone https://github.com/<you>/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform.git
cd CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform
python -m venv .venv
.venv/Scripts/pip install -e ".[dev,mcp]"  # macOS/Linux: .venv/bin/pip
cp .env.example .env                       # then fill in the keys (see below)
```

`DRY_RUN=true` (the default) makes every post and email a logged no-op. Set it to `false` only when you mean to send.

### 2. Database (local Supabase)

The Supabase CLI comes with the frontend's dev dependencies:

```bash
cd frontend && npm install && cd ..
npx --prefix frontend supabase start --workdir .     # Postgres, Auth, Storage, Edge runtime; applies every migration
npx --prefix frontend supabase status --workdir .    # prints the URLs and keys for the next steps
```

In `.env` set:
- `SUPABASE_URL=http://127.0.0.1:54321`;
- `SUPABASE_SERVICE_ROLE_KEY` (from `status`);
- `SUPABASE_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`.

For a hosted project, link it and run `supabase db push` instead. See [docs/REFERENCE.md](docs/REFERENCE.md#database-and-edge-functions).

### 3. Web app

```bash
cd frontend
cp .env.example .env    # VITE_SUPABASE_URL=http://127.0.0.1:54321 and VITE_SUPABASE_ANON_KEY from `supabase status`
npm run dev             # http://localhost:5173
```

Sign up, open the Dashboard and start a campaign.

### 4. Running campaigns

In production the website's Edge Functions dispatch the GitHub Actions workers. Locally, run the worker yourself:

```bash
.venv/Scripts/python -m src.graph.run_campaign "Order-ahead coffee for commuters" --user-id <your Supabase user id>
.venv/Scripts/python -m src.scheduler.run_iteration          # resume campaigns whose gate was decided or whose metrics are due
```

To use the Edge Functions locally (campaign creation from the browser, the API, email setup), serve them with `npx --prefix frontend supabase functions serve --workdir .`.

### 5. Deploying

| Part | Where | How |
|---|---|---|
| **Database and Edge Functions** | Supabase | Pushes to `main` run [`supabase-deploy.yml`](.github/workflows/supabase-deploy.yml): it applies new migrations and deploys every function. It needs these repo secrets: `SUPABASE_DB_URL`, `SUPABASE_ACCESS_TOKEN`, `SUPABASE_PROJECT_REF`. Set the functions' own secrets (`GITHUB_REPO`, `GITHUB_PAT`, `APP_BASE_URL`, `GROQ_API_KEY`, Stripe) with `supabase secrets set`. |
| **Workers** | GitHub Actions | Mirror `.env` as repo secrets. [`campaign-loop.yml`](.github/workflows/campaign-loop.yml) runs hourly and on demand. |
| **Web app** | Vercel (or any static host) | Root directory `frontend`. Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`, then add the site URL to Supabase Auth's redirect URLs. |

Step by step: [docs/REFERENCE.md](docs/REFERENCE.md#deploying-the-frontend).

## Tests

| Suite | Command |
|---|---|
| Python unit (offline: any network access fails the test) | `.venv/Scripts/python -m pytest tests/unit` |
| Database: RLS, functions, isolation (needs the local Supabase) | `.venv/Scripts/python -m pytest tests/integration` |
| Edge Function logic | `node --test supabase/functions/_shared/*.test.ts` |
| Web app: types, lint, browser tests on desktop and phone | `cd frontend && npx tsc -b && npm run lint && npx playwright test` |
| Agent quality (golden set; needs Groq) | `.venv/Scripts/python -m src.eval.run_eval` |

CI runs the tests on every push ([`tests.yml`](.github/workflows/tests.yml)). The agent-quality eval ([`eval.yml`](.github/workflows/eval.yml)) spends the shared Groq budget, so it runs only when started by hand from the Actions tab.

## Project layout

```
src/
  graph/          the LangGraph campaign: nodes, state, run_campaign
  capabilities/   what the agents do: feasibility, audience, creative, decision, crash test,
                  email engine, impact, brand memory, competitors, fatigue, circuit breaker...
  providers/      LLM and image providers, the free-tier gateway, BYOK
  tools/          clients: Bluesky, Mastodon, Reddit, Resend, the bandit, memory, ad composer
  scheduler/      hourly jobs: resume, retries, webhooks, market watch
  prompts/        every production prompt, versioned
  finetune/       the domain classifier's data, training and registry
  mcp_server/     the capabilities as MCP tools
frontend/         the React app (src/) and Playwright tests (e2e/)
supabase/         migrations and Edge Functions
docs/             feature guides, architecture, the developer reference, OpenAPI
```

## Documentation

- **Using the app:** the in-app guide at `/docs`, and the [demo script](docs/DEMO.md).
- **Feature guides:**
  - [decision engine](docs/DECISION_ENGINE.md)
  - [ad templates](docs/AD_TEMPLATES.md)
  - [crash test](docs/CRASH_TEST.md)
  - [email engine](docs/EMAIL_ENGINE.md)
  - [proof of impact](docs/PROOF_OF_IMPACT.md)
  - [brand memory](docs/BRAND_MEMORY.md)
  - [competitor intelligence](docs/COMPETITOR_INTELLIGENCE.md)
  - [creative fatigue](docs/CREATIVE_FATIGUE.md)
  - [circuit breaker](docs/CIRCUIT_BREAKER.md)
- **For developers:**
  - [architecture](docs/architecture.md)
  - [developer reference](docs/REFERENCE.md): configuration, roles, privacy, billing, API, MCP and more
  - [OpenAPI](docs/openapi.yaml)
  - [changelog](CHANGELOG.md)
