# CampaignIQ developer reference

The technical detail behind the [README](../README.md): configuration, the pieces of the platform and how they're enforced. Feature guides live next to this file (decision engine, crash test, proof of impact, brand memory, email engine and more).

## How a campaign runs

The graph is LangGraph (`src/graph/build_graph.py`), checkpointed in Postgres (`SUPABASE_DB_URL`) so a run survives across the separate, short-lived GitHub Actions jobs that execute it:

1. **Intake, feasibility, audience, decision.** Idea → category (the fine-tuned classifier or the LLM) → feasibility score from live signals → personas → the decision engine's recommendation.
2. **Gate 1.** A person approves, edits (category, personas, email audience) or rejects. The graph pauses here; `resume-campaign` restarts it the moment the decision is saved.
3. **Creative.** The LinUCB contextual bandit (`tools/bandit.py`, 20 arms: 5 image styles × 4 copy tones) picks a style and tone. Copy and the ad are generated, checked for novelty against the organisation's past work (`tools/memory.py`, multilingual pgvector embeddings), pre-tested on a synthetic persona panel, then crash-tested.
4. **Gate 2.** A person approves the exact ad (and may edit the copy).
5. **Distribution.** Bluesky, Mastodon, Reddit (when enabled) and email, each through the delivery ledger.
6. **Metrics and feedback.** After `METRICS_WAIT_HOURS`, engagement and email clicks become a reward for the bandit. `feedback_correction.py` decides whether to run another round (free: 3 rounds, paid or BYOK: 10) or stop, and writes a closing summary.

`campaign-loop.yml` runs both the hourly sweep (resumes whatever is ready, retries deliveries, runs the schedulers) and immediate per-campaign runs dispatched by the Edge Functions.

**Provider tiers,** resolved per user: their own key (BYOK, stored in Supabase Vault through `submit-provider-key`; only the workers can read it), then the platform's paid key if they subscribe, then the free tier (Groq and fallbacks, see the LLM gateway). LangSmith tracing is optional (`LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY`).

`sentence-transformers` pulls in `torch` (~1 GB). If `pip install` drops mid-download, run it again; pip resumes.

## Environment and keys

Installing and running are in the [README](../README.md#getting-started). Required free-tier keys (the system runs fully free without any paid key):

| Key | Where to get it |
|---|---|
| `GROQ_API_KEY` | console.groq.com |
| `NEWSAPI_KEY` | newsapi.org |
| `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` | bsky.app Settings → App Passwords |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `RESEND_TEST_TO_EMAIL` | resend.com |
| `MASTODON_POST_TOKEN` (optional) | Your Mastodon instance → Preferences → Development → New application, scopes `write:statuses` + `write:media`. Set → every approved round is also posted to Mastodon with its ad; empty → the channel is off. Separate from the read-only `MASTODON_ACCESS_TOKEN` used for search. |

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
**delivery ledger** ([`capabilities/delivery.py`](../src/capabilities/delivery.py),
`deliveries` table). It guarantees the following:
- **Once per round:** the same campaign/round/channel is sent at most once, even across separate GitHub Actions runs or two workers at the same time (atomic claim).
- **A failing channel can't crash a run:** it's retried three times in-process, then rescheduled with backoff (5 min, 30 min, 2 h, 8 h) by `src.scheduler.retry_deliveries`, which runs in the hourly sweep.
- **Dead-letter state:** after 5 attempts the send is marked `dead`, and `OPS_ALERT_EMAIL` gets an alert.
- **No ledger, no send:** a send never happens without a ledger claim.

Without Supabase credentials (local scripts), a local JSON file stands in for the ledger.

### Brand-safety guardrails

[`src/capabilities/guardrails.py`](../src/capabilities/guardrails.py) checks every generated creative. It's deterministic and free, with no LLM call.

| Severity | Triggers | What happens |
|---|---|---|
| **block** | A link to anything but the campaign's CTA domain, an email address or phone number, a banned term (built-in list + `BANNED_TERMS`), over 300 characters for Bluesky (500 for Mastodon), empty copy | The copy is regenerated with the reasons, up to 2 times. If it's still blocked, Gate 2 shows why and distribution refuses to send. |
| **review** | Absolute claims ("guaranteed", "risk-free", "#1", "clinically proven") and category-specific claims ("cures", "guaranteed returns", "lose 10 kg") | Shown at Gate 2 for the approver to substantiate. |

Healthcare, finance and fitness campaigns automatically get a disclaimer: the full text on emails, and a short form on Bluesky and Mastodon when it fits. Results are stored per round in `iterations.guardrail_flags`.

### Email A/B tests

Tick **A/B test emails** in the composer, which needs at least 2 recipients. Each round then works like this:
1. **Variant B is written.** A `generate_variant_b` step between pre-flight and Gate 2 writes it with the LinUCB bandit's **second-best** arm. It runs once per round and outside the gate, which re-runs on resume, so the B the approver sees is the B that's sent.
2. **The list is split.** It's sorted and divided in two, so the split is the same every time. Each half gets one variant: A on `email`, B on `email_b`, each with its own delivery and click tracking ([`capabilities/experiments.py`](../src/capabilities/experiments.py)).
3. **Results are compared.** Click rates go through a two-sided two-proportion z-test, and a winner is declared only when p < 0.05. The result sits on the variant-B metric and shows on the Metrics page.
4. **The bandit learns from both.** Each variant's reward updates its own arm, using the email context.

### Brand kit

Each organisation's kit (Settings → Brand kit, edited by owners and admins; [`capabilities/brand.py`](../src/capabilities/brand.py)) is applied in three places:
- **Creative generation** follows the **voice**, which is fenced as user text, and the **preferred words**.
- **Forbidden words** join the brand-safety banned terms, so a draft using one is rewritten and can never be sent.
- **The required sign-off or hashtag** is appended to Bluesky and Mastodon posts (when it fits) and emails that don't already contain it.

With no kit set, prompts are exactly what they were before.

### Prompt-injection protection

Untrusted text reaches the prompts from two places:
- **Third parties:** news headlines feed the feasibility rationale.
- **Users:** the idea, stakeholder comments and past campaigns, plus model output derived from them (personas, copy) that gets passed to the next step.

[`src/security/prompt_guard.py`](../src/security/prompt_guard.py) handles both:
- **Fencing:** every untrusted value goes inside an `<untrusted source=... id=random>` block, and fake closing tags inside the value are neutralised. Every system prompt adds the rule that fenced text is data, never instructions.
- **Clean-up:** control and bidi characters are stripped, and length is capped.
- **Filtering:** headlines that read like instructions ("ignore previous instructions", role tags, "reveal your prompt", …) are dropped and logged.

Outputs are schema-checked: an off-list category becomes `other`, and personas and the bandit use fixed label sets. That limits what a successful injection could change.

### `track-click` (email link tracking)

Outgoing emails route their CTA link through a Supabase Edge Function so
click data doesn't depend on Resend's own tracking. Set it up once:

1. Create a free project at supabase.com and apply the schema (see
   [Database and Edge Functions](#database-and-edge-functions)).
2. Deploy the `track-click` function
   ([`supabase/functions/track-click/index.ts`](../supabase/functions/track-click/index.ts)).
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

All of `supabase/functions/` is deployed by [`supabase-deploy.yml`](../.github/workflows/supabase-deploy.yml) (see [Database and Edge Functions](#database-and-edge-functions)). JWT verification is set per function in `supabase/config.toml`; it's off only where the caller isn't a signed-in user.

| Function | What it's for | JWT | Secrets it needs |
|---|---|---|---|
| `create-campaign`, `resume-campaign`, `trigger-capability-run` | Start a campaign, resume it after a gate or stop, run one Tools capability (they dispatch the GitHub Actions workflows) | on | `GITHUB_REPO`, `GITHUB_PAT` |
| `submit-provider-key` | Store a BYOK key in Vault | on | none |
| `persona-chat` | Chat with a persona | on | `GROQ_API_KEY` |
| `billing` / `stripe-webhook` | Stripe Checkout and portal / Stripe's events (signature-checked) | on / off | `STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `APP_BASE_URL` / `STRIPE_WEBHOOK_SECRET` |
| `delete-account` | Erase a user's account | on | none |
| `api` | The public REST API (organisation keys) | off | `GITHUB_REPO`, `GITHUB_PAT` (for `POST /v1/campaigns`) |
| `track-click` | Email link clicks | off | none |
| `email-setup`, `email-test` | Connect a brand's Resend account; Gate 2's "Send me a test" | on | `PUBLIC_FUNCTIONS_URL` (optional) |
| `resend-webhook` | Resend's delivery events (Svix-signed, per organisation) | off | none |
| `unsubscribe`, `join` | The public unsubscribe and sign-up pages behind campaign emails | off | `APP_BASE_URL` |

`SUPABASE_URL`, `SUPABASE_ANON_KEY` and `SUPABASE_SERVICE_ROLE_KEY` are injected into every function automatically. Set the others once with `supabase secrets set`. The GitHub Actions side needs every key in `.env` mirrored as a repo secret (Settings → Secrets and variables → Actions); `campaign-loop.yml` and `capability-run.yml` list exactly which ones in their `env:` blocks.

## Database and Edge Functions

The schema lives in [`supabase/migrations/`](../supabase/migrations/), managed with the Supabase CLI (a frontend devDependency: `npx --prefix frontend supabase ... --workdir .`). [`20261021000000_baseline.sql`](../supabase/migrations/20261021000000_baseline.sql) is a `supabase db dump` of production; it replaces the hand-run `src/db/schema_*.sql` files.

- **New schema change:** `npx --prefix frontend supabase migration new <name> --workdir .`, write the SQL, and push. Never edit an applied migration.
- **Every change** is checked by [`supabase-check.yml`](../.github/workflows/supabase-check.yml), which builds a fresh database from all migrations in Docker and lints it. It never touches production.
- **On main,** [`supabase-deploy.yml`](../.github/workflows/supabase-deploy.yml) applies pending migrations to production (`SUPABASE_DB_URL`; must be the IPv4 Session-pooler string) and deploys the Edge Functions (`SUPABASE_ACCESS_TOKEN` + `SUPABASE_PROJECT_REF`, skipped until they're set). The first run records the baseline as already applied instead of re-running it.
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

## Privacy and data (GDPR)

- **Export (right of access and portability):** Settings → Privacy & data downloads `export_my_data()`. That covers the account, memberships, campaigns the user created (with personas, rounds, metrics, feedback and gates), votes, category corrections, templates, masked keys, Tools runs, AI usage, private memory and their own audit events. It never includes secrets.
- **Erasure:** the [`delete-account`](../supabase/functions/delete-account/index.ts) Edge Function, which requires `{"confirm": "DELETE"}`, works in two steps:
  1. `prepare_account_deletion()` (service role only) refuses while the user is the last owner of a team that has other members. Otherwise it hands their team campaigns to another owner or admin, and deletes organisations where they're the only member, including their personal one.
  2. The auth user is deleted, and every personal table cascades from it. That includes BYOK secrets in Vault and the category corrections the weekly retrain would use.
- **Retention:** `apply_retention()` runs in the hourly sweep:

  | Data | Kept for |
  |---|---|
  | Tools results | 90 days |
  | Per-call AI usage | 180 days |
  | Delivered-send payloads (recipients, email HTML) | 30 days; failed sends keep theirs for retries |
  | Raw click events | 1 year |

  The audit log is kept, and refers to people only by ID.

## Approval flows

Gates are decided by **votes**: each owner, admin or approver adds one to `gate_approvals`. A database trigger then decides the gate:
- **Reject:** any reject rejects it.
- **Approve:** otherwise it's approved once the organisation's **required approvals** (1–5, default 1) are in; it's "approved with edits" if anyone edited.

Users can't update `gate_decisions` directly any more, so the quorum can't be skipped. Every vote is recorded in the audit log.

**Approval policy** (Settings → Team, owners and admins):
- **Required approvals:** 1 to 5 per gate.
- **No self-approval:** optionally, the campaign's creator can't vote on it.
- **Deadline:** an approval deadline in hours. Gates past it are escalated once to owners and admins by the hourly sweep.
- **Slack:** an incoming-webhook URL for notifications.

**Notifications** (`src/notifications.py`): a waiting gate reaches the organisation's **designated approvers** (Settings → Team; nobody chosen means everyone who can approve) in the app (the bell), by email (from the brand's own connected Resend address, or the app's with `NOTIFY_EMAIL=true`; each person can turn email off) and on Slack. Overdue approvals, critical holds and paused email go to owners and admins. Links point at `APP_BASE_URL`; voting stays in the app, signed in, so role and quorum rules always apply.

## Campaign calendar

`/calendar` shows the active organisation at a glance:
- **Month grid:** campaigns started, rounds sent (from the delivery ledger, so it reflects real sends) and results due (send time + `METRICS_WAIT_HOURS`), in the viewer's time zone. On phones the events collapse to coloured dots.
- **Waiting on approval:** every open gate, with how long it has waited.
- **Portfolio:** every campaign with status, round progress, best reward, start date and last activity.

## Collaboration

- **Discussion:** a live comment thread on each campaign page (`campaign_comments`), about the whole campaign or one round. Anyone in the organisation can read and comment; people edit their own comments, and managers can remove any.
- **Copy editing at Gate 2:** owners, admins and approvers can rewrite variant A or B before voting.
  - **Versions:** `edit_round_copy()` stores every version in `copy_revisions`, keeping the AI draft as version 1 so any version can be restored. Each edit goes in the audit log.
  - **Timing:** edits are only accepted while that round's Gate 2 is open.
  - **What's sent:** after approval, the Gate 2 step reloads the edited text, so the approved copy is what goes out, still subject to the send-time brand-safety check.

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

## Prompt registry

Every production prompt lives in [`src/prompts/catalog.py`](../src/prompts/catalog.py) with an id and a semantic version (`creative.generate@1.0.0`, …). Capabilities render them with already-fenced values; the registry adds the injection rule to the system prompt.

- **Versions are locked to content.** [`fingerprints.json`](../src/prompts/fingerprints.json) records a hash of each prompt, and `tests/unit/test_prompts.py` fails if the text changes without a version bump. To change a prompt:
  1. Edit it.
  2. Bump its version (patch for wording, minor for new instructions, major for a new output format) and add a CHANGELOG line.
  3. Run `python -m src.prompts --update-fingerprints`.
- **Traceable.** Every LLM call records `id@version` in `llm_usage.prompt` and in its Langfuse generation, so a jump in failures, tokens or quality can be tied to the prompt change behind it. `python -m src.prompts` lists the current versions.
- **Regression gate.** `python -m src.eval.run_eval` fails below the 60% overall threshold, or when any metric drops more than 5 points below [`src/eval/baseline.json`](../src/eval/baseline.json), the last accepted run. After an intended change, accept the new scores with `--update-baseline`. That records the prompt versions too.

## Observability

All optional and free-tier; each part switches on only when its keys are set ([`src/observability.py`](../src/observability.py)):

| | What you get | Turn on with |
|---|---|---|
| **In-app** (always on) | Settings → AI usage & reliability: calls, failures, tokens and p50/p95 latency per provider per day for the organisation (`llm_usage_stats()`) | — |
| **Langfuse** | A trace per run: a span per graph step (gate pauses are marked as pauses, not errors) and a generation per LLM call, with provider, model, tokens, latency, failures and fallbacks | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (+ `LANGFUSE_HOST`) |
| **Sentry, workers** | Uncaught errors with release and service tags | `SENTRY_DSN` |
| **Sentry, browser** | Errors caught by the app's error boundary, which also shows a recovery screen. The SDK only downloads when configured. | `VITE_SENTRY_DSN` (Vercel env) |

**Langfuse privacy:** prompts carry customers' campaign content, so traces hold metadata only. Set `LANGFUSE_CAPTURE_CONTENT=true` to include prompt and response text.

The Python packages come from `pip install -e ".[observability]"`.

## Billing (Stripe)

Settings → Plan & billing: owners upgrade through **Stripe Checkout** and manage cards and invoices in Stripe's **customer portal**. There's no Stripe SDK; [`_shared/stripe.ts`](../supabase/functions/_shared/stripe.ts) calls the REST API.

- [`billing`](../supabase/functions/billing/index.ts) creates the Checkout or portal session; only owners may.
- [`stripe-webhook`](../supabase/functions/stripe-webhook/index.ts) verifies `Stripe-Signature` (HMAC, 5-minute replay window; unit-tested under Node) and calls `apply_billing()`. That's the only way billing changes a plan:
  - **Statuses:** `active`, `trialing` and `past_due` mean Pro; anything else means free.
  - **Personal organisations** flip the owner's subscription, which also unlocks paid providers.
  - **Team organisations** flip the organisation's plan.

**Setup (test mode):**
1. In Stripe (test mode), create a recurring Price for "Pro".
2. In Supabase Edge Function secrets, set `STRIPE_SECRET_KEY=sk_test_…`, `STRIPE_PRICE_PRO=price_…` and `APP_BASE_URL`.
3. Add a webhook endpoint at `…/functions/v1/stripe-webhook` for `checkout.session.completed` and `customer.subscription.*`, and set its `STRIPE_WEBHOOK_SECRET=whsec_…`.
4. Pay with the test card `4242 4242 4242 4242`.

## Onboarding, docs and status

- **Onboarding:** a Dashboard checklist with six steps, each worked out from real data, so it can't be ticked off by clicking: choose a username, start a campaign, approve a gate, set a brand kit, create a team, connect Slack or the API. It can be dismissed.
- **Docs:** `/docs` is the product guide for users. This file is the developer reference.
- **Status:** [`uptime.yml`](../.github/workflows/uptime.yml) runs [`src/scheduler/uptime.py`](../src/scheduler/uptime.py) every 15 minutes to probe the website, database API, sign-in, Edge Functions and public API.
  - **Where results go:** they're written to `status_checks` and kept 30 days.
  - **The public page:** `/status` reads `status_summary()`, which anyone may call; it returns only up/down, latency and uptime percentages, and the raw rows stay private under RLS.
  - **Secrets:** the workflow needs `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` and optionally `SUPABASE_ANON_KEY`.

## Admin console

`/admin` is for **platform operators**, not organisation owners. Grant access with `python -m src.admin.make_admin you@example.com` (add `--revoke` to remove it). The page shows:
- **Health tiles:** users, organisations, active and new campaigns, AI tokens and failures, dead sends, failed webhooks, paid organisations.
- **Organisations:** searchable by name or owner email, with a plan override.
- **The dead-letter queue:** give a dead send one more retry.
- **Feature flags:** toggle and set rollout percentages.
- **Audit chain:** one-click verification.

Every admin function checks `is_platform_admin()` in the database and is written to the audit log under the operator's own user ID. There's deliberately no impersonation.

## Audit log

`audit_log` is written by **database triggers**, so no path (frontend, workers, Edge Functions, the SQL editor) can skip it.
- **What's recorded:** campaign creation, status changes, stops and category corrections; gate decisions with comments; members added, re-roled or removed; invitations created, accepted or revoked; organisation renames; BYOK keys added, rotated or deleted (capability and masked key only); deliveries sent or dead-lettered; feature-flag changes. Each event records who did it, or `system` for workers.
- **Integrity:** every row stores the SHA-256 of the previous one, so `verify_audit_chain()` (service role) returns the first row whose hash doesn't match, or null when the chain is intact. A trigger blocks UPDATE, DELETE and TRUNCATE, and no role can write the table directly.
- **Access:** org owners and admins browse and export it as CSV or JSON in Settings → Audit log.
- **Never logged:** secrets, invite tokens and delivery payloads.

## LLM gateway (free-tier fallback)

Free-tier LLM calls go through [`src/providers/gateway.py`](../src/providers/gateway.py), which tries each provider in order: Groq, then whichever of **Cerebras** (same `gpt-oss-120b` model), **OpenRouter** (`gpt-oss-120b:free`) and **Gemini Flash** has an API key set. All three have free tiers; see `.env.example`.

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
- [`CHANGELOG.md`](../CHANGELOG.md) follows Keep a Changelog.
- Pushing a tag `vX.Y.Z` runs [`release.yml`](../.github/workflows/release.yml). It checks that the tag and both version fields agree, then publishes that version's changelog section as the GitHub Release.

## Tests

[`tests.yml`](../.github/workflows/tests.yml) runs on every push. It's free: no Groq, no live Supabase.

| Suite | What it covers | Run locally |
|---|---|---|
| **Python unit** (`tests/unit`) | LLM-JSON repair, BYOK crypto, provider tiers, feasibility weighting and graceful degradation, DRY_RUN and dedup, click tracking, LinUCB, graph routing, Gate 1 category corrections, the classifier's retrain gate, and the MCP server (in-memory client) | `pytest -m "not integration"` |
| **RLS integration** (`tests/integration`) | Against a real Postgres built from `supabase/migrations`: cross-user isolation, no self-upgrade of subscriptions, masked BYOK view, signup trigger, Realtime publication | `npx --prefix frontend supabase db start --workdir .` then `pytest -m integration` |
| **Frontend e2e** (`frontend/e2e`, Playwright) | Every public page on desktop and a phone, no sideways scroll at 360/390/430 px, the phone menu, the auth redirect, 404, theme persistence | `cd frontend && npm run test:e2e` |

- **Install:** `pip install -e ".[dev,mcp]"`.
- **Network guard:** a unit test that tries to open a non-loopback connection fails.
- **Coverage floor:** 60%. Raise it as coverage grows.

## Eval harness

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
what `.github/workflows/eval.yml` runs when started by hand (Actions → Eval → Run workflow), with
`GROQ_API_KEY`/`NEWSAPI_KEY` configured as repo Actions secrets (Reddit
secrets are optional/on hold, same as local `.env`).

## Fine-tuned domain classifier

Every campaign starts by classifying the idea into one of 12 product domains.
That label is the bandit's domain context, so it decides which past campaigns a
new one learns from. The classifier distils that decision from the production LLM
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

**Human corrections.** Gate 1 shows the predicted category in a dropdown; if the user changes it, the campaign is updated (the graph re-reads it after the gate, so the bandit uses the corrected context) and the fix is stored in `domain_corrections` as a human-verified training label. The table is part of [`supabase/migrations/`](../supabase/migrations/).

**Weekly retrain** ([`retrain-domain-model.yml`](../.github/workflows/retrain-domain-model.yml), Sundays 03:00 UTC, or run it by hand with *force*). No Groq calls:

1. `python -m src.finetune.retrain prepare`: synthetic train/val plus every human correction (weighted ×3; a correction overrides the teacher's label for the same idea). It skips the week if there are fewer than 30 new corrections since the published model's `training_meta.json`. About 1 in 5 corrections is held back for the gate and never trained on.
2. Train on a free Kaggle T4 ([`src/finetune/kaggle/train_kernel.py`](../src/finetune/kaggle/train_kernel.py), same recipe as the notebook) via a private Kaggle dataset and kernel.
3. `retrain evaluate`: the candidate and the current model are compared on the golden set (human labels), the held-back corrections (human labels) and the held-out synthetic test (teacher agreement, 3-point slack). The candidate is promoted only if it is not worse on any of them.
4. `retrain promote`: upload the GGUF and `training_meta.json` to the private HF repo. The other workflows pick it up on their next run.

**First run (2026-10-21)** was forced, with 0 corrections, so it trained on the same synthetic data as the Colab model. It took 22 minutes, 17 of them on Kaggle. Both models were scored on the same CI runner:

| Model | Golden (human labels) | Held-out (teacher agreement) |
|---|---|---|
| Current (Colab v1) | 78% (14/18) | 72% |
| Candidate (Kaggle) | 83% (15/18) | 78% |

The candidate was promoted. The same v1 file scored 83% / 75% on a Windows laptop: llama.cpp builds can flip a borderline greedy decode, so the gate always scores both models in the same job.

Secrets: `KAGGLE_USERNAME`, `KAGGLE_KEY` (the Kaggle account must be phone-verified for GPU and internet), `SUPABASE_*`, `DOMAIN_MODEL_HF_REPO`, and `HF_WRITE_TOKEN` (a write-scoped HF token; falls back to `HF_TOKEN`).

**Model registry** ([`src/finetune/deployments.py`](../src/finetune/deployments.py), `model_deployments` table). Each promoted model is a commit in the private Hugging Face repo, and the registry pins which commit serves traffic:

| Command (`python -m src.finetune.deployments …`) | Effect |
|---|---|
| `list` | Promoted versions with their gate metrics; `*` marks the one being served |
| `status` | What's deployed, plus shadow agreement so far |
| `rollback` | Serve the previous version again |
| `activate <rev>` | Serve any version |
| `shadow <rev>` | Run `<rev>` on every idea next to the active model and log only whether they agree (an idea hash, no text) |
| `canary <rev> <pct>` | `<pct>`% of ideas, picked stably by a hash of the idea, use `<rev>` |
| `off` | End shadow or canary |

The weekly retrain records each promotion and keeps the previous version, so rollback is always one command. Changes are written to the audit log. If the registry can't be read, the latest model is served.

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

## Public API and webhooks

**REST API:** the [`api`](../supabase/functions/api/index.ts) Edge Function, documented in [`docs/openapi.yaml`](../docs/openapi.yaml). Authenticate with an organisation key: `Authorization: Bearer ciq_…` (keys issued earlier as `mos_…` still work).

| | |
|---|---|
| `GET /v1/campaigns` | List campaigns (`limit`, `status`) |
| `GET /v1/campaigns/{id}` | One campaign, with its rounds and metrics |
| `POST /v1/campaigns` | Start a campaign (scope `write`; plan limits apply, 429 with the reason) |
| `GET /v1/usage` | Plan, limits and usage |

- **Keys** are created by owners and admins in Settings → API & webhooks. A key is shown once and stored as a SHA-256 hash, and every key action goes in the audit log.
- **Rate limit:** 60 requests per minute per key (429 with `Retry-After`).
- **Org scope:** every query is pinned to the key's organisation.

**Webhooks:** any audit event (`*`, an exact action, or a prefix such as `gate.*`) can be POSTed to the organisation's HTTPS endpoints. Each request carries:
- `X-CampaignIQ-Event`, the event name;
- `X-CampaignIQ-Delivery`, a unique ID to de-duplicate on;
- `X-CampaignIQ-Signature: sha256=<HMAC-SHA256(secret, raw body)>`.

For now each delivery also carries the same three values under the old `X-MarketingOS-*` names, so receivers built before the rename keep working; switch to the new names, as the old ones will be dropped.

The **first attempt is sent by the database the moment the event happens** (`pg_net`, from the audit-log trigger). [`src/scheduler/webhooks.py`](../src/scheduler/webhooks.py), in the hourly sweep, confirms responses and retries failures with backoff (1 min → 8 h, 6 attempts in all). "Send test" fires a `ping`.

## MCP server

[`src/mcp_server/server.py`](../src/mcp_server/server.py) exposes the same `capabilities/` functions the graph, the Tools page and CI use. It wraps them, it doesn't reimplement them, so Claude Desktop, Claude Code or any other MCP client gets exactly the app's behaviour.

| Tool | What it does |
|---|---|
| `classify_idea` | Normalizes the idea and picks its category (the fine-tuned model when installed, else the LLM) |
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
pip install -e ".[mcp]"          # plus ".[local-model]" for the fine-tuned classifier
python -m src.mcp_server.server  # stdio; add --http 8765 for streamable HTTP on 127.0.0.1
```

Claude Code: `claude mcp add campaigniq -- <repo>/.venv/Scripts/python.exe -m src.mcp_server.server` (works from any directory; the server loads the repo's `.env` itself).
Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "campaigniq": {
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
at 0.9 cosine similarity). (`campaigns.target_language`, in [`supabase/migrations/`](../supabase/migrations/).)

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
   - **Site URL**: the production URL, e.g. `https://campaigniq.vercel.app`.
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
