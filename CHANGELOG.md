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
