# Email engine: sending campaign emails to a brand's own customers, legally

Status: design, settled in review on 2026-10-26, waiting for final approval.

## 1. Intent

CampaignIQ writes and sends marketing campaigns for **brands**: our users, each an *organisation*. The email channel must reach **the brand's own customers and subscribers**, the people who opted in to hear from that brand, the way large brands do it legally.

**Finding new people.** Strangers' addresses are never found or scraped. Brands reach new interested people through the channels CampaignIQ already posts to (Bluesky, Mastodon, Reddit). Those posts carry the brand's **sign-up link**, and people who confirm join the list.

**Why this is needed.** Today:
- a campaign's recipients are a bare `campaigns.email_to text[]`, and the web app never fills it in, so every campaign emails only the test inbox;
- there are no contacts, no consent records, no unsubscribe, no bounce handling and no postal address.

Sending real campaigns from that base would break:
- the EU and UK consent rules;
- India's DPDP Act;
- CAN-SPAM;
- Gmail and Yahoo's bulk-sender rules;
- Resend's acceptable-use policy (section 9).

## 2. Decisions (all made by the user)

| # | Decision |
|---|---|
| D1 | **Legal model only.** Email only people with a recorded opt-in. No scraping, no bought lists, no cold email. |
| D2 | **Brands supply their own customers' addresses.** CampaignIQ's own users are never campaign recipients. |
| D3 | **Each brand connects its own Resend account.** Its domains, limits (free plan: 3 domains, 3,000 emails a month, 100 a day) and reputation stay its own. |
| D4 | **Without a connected account, email goes to the test inbox only.** That's today's sandbox sender to `RESEND_TEST_TO_EMAIL`. CampaignIQ owns no domain. |
| D5 | **One email per person per campaign, sent in batches across rounds.** |
| D6 | **The full-access key is used only during setup.** CampaignIQ stores only a **sending-only key restricted to the chosen domain**, which it creates through Resend's API. |
| D7 | **Owners, admins and marketers see and import addresses.** Viewers see counts and segment sizes only. |
| D8 | **One consent type: opted in, with a source** (checkout, sign-up form, in-store, event, API, other). Purchase history is data for segments. A **24-month inactivity sunset** applies: no click and no purchase in 24 months means no more sends. |
| D9 | **The sign-up form always uses double opt-in.** It can't be turned off. |
| D10 | **A sending window per brand**, default 09:00–20:00 in the brand's time zone. |
| D11 | **A `{first_name}` placeholder with a fallback greeting.** No AI-written email per person. |
| D12 | **Unsubscribe is all-or-nothing per brand.** There is no topic preference centre. |
| D13 | **Segments match the campaign's language by default** (same language or unknown). Brands can switch this off. |
| D14 | **Contact caps by CampaignIQ plan:** free 1,000; pro and enterprise unlimited. The cap is a column in `plan_limits`. |
| D15 | **Email can't be switched on until our Resend webhook is installed.** With only a sending key, the webhook is our only source of bounce and complaint data. If the brand's webhook slot is taken, setup asks them to free it or upgrade their Resend plan. |
| D16 | **Every campaign link carries a per-person tracking token.** A click updates that contact's last engagement, and the footer's privacy line mentions click tracking. |
| D17 | **A recorded conversion that matches a contact updates their purchase data** (`POST /v1/conversions`) and counts as engagement. |
| D18 | **Outside the sending window, only the email batch waits.** Other channels post as normal. |
| D19 | **At the contact cap:** an import adds people up to the cap and lists the rest as not added. The sign-up form accepts up to 10% over and then closes politely. Managers are notified at 90% and 100%. |
| D20 | **Only owners and admins can export or erase.** Erasing leaves a permanent suppression hash, and both actions are audited. |
| D21 | **Customer-facing pages and emails follow the person's language:** their choice on the form, otherwise the campaign's language. That covers the sign-up form, confirmation email and unsubscribe page, in the app's 5 locales with English as fallback. |
| D22 | **The AI never sees personal data**, only tag names, field names and counts. A test enforces this. |
| D23 | **Social posts end with the brand's sign-up link** when email is connected. It's on by default with a per-campaign switch, and the link carries the campaign id. |
| D24 | **One sign-up form per brand.** Sign-ups are auto-tagged `signed-up`, plus `from:<campaign>` when they arrive through a campaign link. |
| D25 | **People can delete their own data from the unsubscribe page** ("Also delete my details"). This erases them, leaves the suppression hash, and audits it as "erased by the person". |
| D26 | **Bounces:** a hard bounce suppresses the person at once; so do 3 soft bounces in a row. |
| D27 | **Stopping a campaign cancels its waiting emails.** Their ledger status becomes `cancelled`. |
| D28 | **Sandbox mode:** a key whose account has no verified domain connects in sandbox mode. Everything runs, but every email is redirected to the Resend account owner's own address and labelled "[Sandbox: would have gone to N people]". It's clearly labelled everywhere. This is how the engine is demonstrated without a domain. |

## 3. Goals, non-goals, anti-goals

**Goals:** everything in section 2, built so the parts that work today keep working on the resolved recipients:
- one email per person;
- the delivery ledger with idempotency;
- click tracking;
- A/B variants;
- proof-of-impact holdouts;
- the circuit breaker.

**Non-goals (this round):**
- B2B cold email;
- Shopify, WooCommerce or CRM connectors (the API covers these for now);
- a shared CampaignIQ sending domain;
- open tracking (unreliable since Apple Mail Privacy Protection);
- a drag-and-drop email designer;
- a topic preference centre;
- re-permission campaigns;
- Resend Broadcasts or Audiences. We need per-person sends with tracking tokens and experiment arms.

**Anti-goals (failure even if it works):**
- Any email to a contact who isn't `subscribed`, is suppressed or is past the sunset. Sandbox redirects to the account owner are the only exception.
- An import or API call that re-subscribes someone who unsubscribed, bounced, complained or was erased. Only the person can re-subscribe, through double opt-in.
- A campaign email without a working unsubscribe link and one-click header.
- One organisation seeing, counting or emailing another organisation's contacts.
- Any Resend key, full or sending-only, reaching the browser, logs, the AI model or any SQL a user can run.
- A contact's personal data reaching the AI model.
- One person getting the same campaign twice.

## 4. Constraints

- The stack stays:
  - the Python/LangGraph worker in GitHub Actions;
  - Supabase (Postgres with RLS, Vault, Deno Edge Functions);
  - the Vite/React frontend;
  - the Resend Python SDK.
- No new paid services, and no new installs without asking.
- **Secrets** live in **Supabase Vault**, following `20261021000600_vault_provider_keys.sql`: a pointer, a masked copy, and SECURITY DEFINER store and read functions callable only by the service role. That table is per user; email secrets are per organisation, so they get a new table.
- **Roles** use the existing `org_can`; see D7 and D20.
- **Standing project rules:**
  - no FLUX calls in tests;
  - one flaky API never crashes a run;
  - all UI text in 5 locales;
  - no sideways scroll at 320 px;
  - no coloured side stripes or blank gaps.

## 5. Design

### 5.1 Connecting Resend (Settings → Email sending)

**Setup** is a manager-only Edge Function, `email-setup`. The brand pastes a **full-access** key once, and the function:
1. Calls `GET /domains`.
   - **No verified domain:** offer **sandbox mode** (D28) and show how to verify one: the SPF, DKIM and return-path DNS records plus a recommended DMARC record. For sandbox redirects the brand types the email address it uses to log in to Resend. Resend's API doesn't expose that address, so setup checks it with one test send; Resend refuses sandbox sends to any other address. *My call:* in sandbox mode we must keep a key that can send from `onboarding@resend.dev`, and Resend's domain restriction can't target the sandbox domain. So we create a sending-only key with no domain restriction, which is still send-only.
   - **Verified domains:** the manager picks one, then a from address on it, a from name and an optional reply-to.
2. Calls `GET /webhooks`.
   - If the plan's slot is taken, it stops with "free your webhook slot or upgrade" (D15).
   - Otherwise it calls `POST /webhooks` for `email.delivered`, `email.bounced`, `email.complained` and `email.delivery_delayed`, pointed at `…/functions/v1/resend-webhook/{org_id}`, and stores the `signing_secret` in Vault.
3. Calls `POST /api-keys` with `permission: sending_access`, restricted to the chosen domain, and stores **that** key in Vault.
4. **Discards the full key.** It's never written anywhere: not the database, not logs.
5. Requires a **postal address** and **privacy-policy URL** in the brand kit, and a **time zone** and sending window, before email can be switched on.

**State:** a new `org_email_settings` table, one row per org:
- `mode` (`sandbox` or `live`), `sending_key_secret_id`, `masked_key`;
- `from_email`, `from_name`, `reply_to`, `domain`, `domain_id`, `sandbox_to`;
- `webhook_id`, `webhook_secret_id`, `webhook_ok_at`;
- `daily_limit` (default 100), `send_window_start`, `send_window_end`, `timezone`;
- `paused_reason`, `connected_at`.

**To reconnect, change domain or move from sandbox to live,** the brand runs setup again with a full key. The old sending key is left for the brand to revoke; the screen tells them.

**Health:**
- An invalid key or a Resend 401/403 pauses email for the org and notifies managers.
- No webhook event for 72 hours while sends happened shows a "check your webhook" warning.

### 5.2 Contacts, consent, suppression

**`contacts`:**
- `org_id`, `email` (lowercased and trimmed; unique per org), `name`, `first_name`, `language`;
- `tags text[]`;
- `attributes jsonb`: `last_purchase_at`, `orders`, `products[]`, `lifetime_value`, `country`, and anything else imported;
- `status`: `pending`, `subscribed`, `unsubscribed`, `bounced` or `complained`;
- `consent_source`, `consent_note` (for example "website checkout, 2025"), `consent_at`, `consent_text` (the wording shown or attested), `confirmed_at`;
- `last_engaged_at` (click or purchase), `soft_bounces`;
- `created_at`, `updated_at`.

**`contact_events`** is an append-only audit trail:
- event types: `subscribed`, `confirmed`, `imported`, `updated`, `unsubscribed`, `bounced`, `soft_bounced`, `complained`, `clicked`, `purchased`, `erased`, `exported`;
- each event records its source, its actor (a person, the system or the contact) and an IP truncated to /24.

**`email_suppressions`** holds `org_id` and `sha256(lowercased email)`. Unsubscribes, hard bounces, 3 soft bounces in a row, complaints and erasures all land here. Every send and every import checks it.

**Who can write:** only SECURITY DEFINER functions write: `upsert_contacts`, `signup_contact`, `confirm_contact`, `unsubscribe_contact`, `erase_contact`, `record_email_event`, `touch_contact_engagement`. RLS forbids direct writes, and only roles under D7 can read addresses. Viewers get counts through an RPC.

**Rules enforced in SQL:**
- An import or the API may update `name`, `tags` and `attributes` on an existing contact. They never change status, and never add a suppressed address.
- Only `confirm_contact` (the person clicking their confirmation link) can lift a suppression caused by an unsubscribe. A complaint or erasure is permanent.
- **Sunset** (D8): sends exclude contacts whose `coalesce(last_engaged_at, consent_at)` is over 24 months old. They stay in the list, labelled "inactive".
- **Erasure** deletes the contact row and its events, writes the suppression hash and one audit row without the address, and clears the person's recipient hashes from `email_sends`.

**Plan cap:** a `max_contacts` column in `plan_limits`, with the D19 behaviour.

### 5.3 How contacts arrive

1. **CSV import** (Contacts page, owner/admin/marketer):
   - Upload, map columns, then preview.
   - Pick a **consent source** and note, and tick the attestation: "Everyone in this file opted in to receive marketing email from us (for example, ticked a box at checkout or signed up). We can show when and how."
   - Invalid, duplicate, suppressed and over-cap rows are skipped and listed.
   - Up to 10,000 rows per file, sent to `upsert_contacts` in chunks.
2. **Sign-up form** at `/join/{org-slug}`: a public page in the brand's logo and colours.
   - Fields: email, optional first name, language, the consent wording and the privacy link.
   - It has a honeypot field and rate limits per IP and per org. It closes politely at 110% of the cap.
   - A submission creates a `pending` contact and sends a confirmation email through the brand's key, or the sandbox redirect. The link expires after 7 days.
   - Confirming makes the contact `subscribed`, tagged `signed-up` plus `from:<campaign>` when `?c=` is present (D24).
   - The form is disabled while email isn't connected.
3. **API:**
   - `POST /v1/contacts` upserts up to 1,000 per call. It requires a `consent` object (source, timestamp, text) per contact or for the batch.
   - `DELETE /v1/contacts/{email}` erases.
   - Both use the `write` scope and the same SQL rules.
4. **Conversions:** `POST /v1/conversions` that matches a contact updates `attributes.last_purchase_at`, `orders` and `products`, and `last_engaged_at` (D17).

### 5.4 Segments and the AI suggestion

**Segments:**
- `segments` holds `org_id`, `name` and `filter jsonb`:
  - `tags_any`, `tags_all`, `tags_none`;
  - `purchased_within_days`, `not_purchased_within_days`, `product_any`;
  - `country_any`;
  - `match_campaign_language` (default true, D13).
- There is a built-in "All subscribers" segment.
- **Eligible** means: matches the filter, `subscribed`, inside the sunset, and not suppressed.

**AI suggestion (D22):**
- After personas are written, an LLM step gets the personas plus the org's **tag names, attribute field names and value counts**. It never gets addresses, names or rows.
- It proposes a filter using only existing tags and fields; invented ones are dropped by a validator.
- Gate 1 shows "Suggested email audience: … · N people". The person accepts, edits, picks another segment or chooses none.

**Campaign columns:**
- `campaigns.segment_id` and `campaigns.email_audience_frozen_at` are added.
- `email_to` stays only for old rows and unconnected orgs (test inbox).
- The API's `email_to` returns 422 on a connected org unless every address is already a subscribed contact; the message points to `/v1/contacts` and `segment_id`.

### 5.5 Sending

**The audience is frozen** when Gate 1 is approved:
- the eligible contacts are written to `campaign_audience` (campaign, contact, a shuffled position salted by the campaign id, and `holdout bool`);
- the proof-of-impact holdout is drawn here from the whole audience and is never emailed.

**Batches (D5):**
- Each round takes the next unsent positions.
- Size is `ceil(remaining / remaining rounds)`, at least 20 when that many remain, limited by the daily limit and the window.
- Every contact is re-checked for status, sunset and suppression just before sending.
- A/B variants split within the batch.
- When the audience is used up, email is finished for the campaign ("email: all N reached") and remaining rounds use the other channels.

**Window and limit (D10, D18):**
- Outside the window, the round's batch is written as `deferred` and the round carries on with the other channels.
- The retry sweep sends deferred rows when the window opens.
- The daily limit counts every email CampaignIQ sends through the brand's key, using a 00:00 UTC day. Up to 10% is reserved for confirmation emails.
- A Resend rate-limit answer defers the rest, never fails it.

**Ledger:**
- `email_sends` sits under the existing per-round `deliveries` row and holds:
  - `contact_id`, `recipient_hash`, `variant`, `resend_id`;
  - `status`: `queued`, `deferred`, `sent`, `delivered`, `bounced`, `complained`, `failed` or `cancelled`;
  - `attempts`, `sent_at`.
- `deliveries`, `claim_delivery`, the experiment exposure guard and the circuit breaker are unchanged.
- Stopping a campaign cancels queued and deferred rows (D27).

**Each email:**
- **Sending:** sent from the org's address with the org's sending key, read from Vault by the service role at send time.
- **Personalisation:** `{first_name}` with a fallback greeting (D11).
- **Headers:**
  - `List-Unsubscribe: <https://…/functions/v1/unsubscribe?t={token}>`
  - `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
- **Footer:**
  - the unsubscribe link;
  - the brand name and postal address;
  - "You're receiving this because you {consent_source phrase}";
  - "Links in this email are tracked so {brand} knows what interests you".
- **Links:** every link is wrapped with a per-person token (D16).
- **Unsubscribe token:** an HMAC of org, contact and campaign; it is not guessable and needs no login.
- **Sandbox (D28):**
  - the batch is resolved and logged as normal;
  - one email per batch goes to `sandbox_to`, with the subject prefix "[Sandbox: would have gone to N people]";
  - the would-be recipients are marked `sent` with `sandbox = true`, so the flows can be demonstrated.
  - *My call:* one redirected email per batch, not one per person, because the free plan allows 100 a day.
- **Not connected (D4):** today's behaviour — the test inbox only, labelled.
- **Failures:** one recipient's Resend error is recorded and retried and never fails the round. An invalid key or domain pauses the org's email and notifies managers.

### 5.6 Unsubscribe, self-erasure, webhook

- **`unsubscribe` Edge Function:**
  - `GET` shows a branded page in the person's language with an "Unsubscribe" button.
  - After unsubscribing, the page offers "Also delete my details" (D25) and a "Resubscribe" link, which goes through double opt-in.
  - `POST` with `List-Unsubscribe=One-Click` unsubscribes immediately and returns 200 with an empty body.
- **`resend-webhook/{org_id}`:**
  - It verifies the Svix signature with that org's secret, and is idempotent on the Svix id.
  - It matches `resend_id` against `email_sends` and ignores unknown ids, which are the brand's own non-CampaignIQ email.
  - It applies:
    - delivered → `delivered`;
    - hard bounce → suppress;
    - soft bounce → `soft_bounces` + 1, and suppress at 3 in a row;
    - complaint → suppress.
- **`track-click`** also calls `touch_contact_engagement` when the token belongs to a contact.

### 5.7 Metrics and safety pause

- The email reward denominator becomes **delivered**, falling back to sent until webhook data arrives.
- Each campaign shows delivered, bounced, complained and unsubscribed for each batch.
- **Safety pause:**
  - It applies once the org's last 30 days of sends total at least 200.
  - The org's email pauses, and managers are alerted, at a **0.06% complaint rate** or a **3% bounce rate**.
  - Those thresholds sit just under Resend's 0.08% and 4% shutdown limits.
  - A manager can resume after acknowledging the warning.

### 5.8 Screens

- **Contacts** (sidebar, Audience group):
  - status counts (viewers see only these);
  - search and filters, and the import wizard;
  - contact detail with consent history;
  - export and erase for owners and admins only;
  - the Segments tab with live counts;
  - an "inactive" label for contacts past the sunset;
  - cap usage.
- **Settings → Email sending:** the setup flow, sandbox/live mode, domain, from address, webhook health, daily limit, window and time zone, the sign-up link with a copy button, and any pause reason.
- **Dashboard composer:** an optional segment picker.
- **Gate 1:** the AI-suggested audience.
- **Gate 2:**
  - the batch size for this round;
  - exclusions by reason (unsubscribed, bounced, inactive, over the limit, outside the window);
  - "Send me a test", which sends one copy to the signed-in user's own address through the brand's key.
- **Campaign detail:** per-batch delivery results and "N of M reached".
- **Public pages:** `/join/{slug}`, confirmation and unsubscribe. They have no app chrome, are excluded from the navbar and sidebar, use the brand's styling, and are offered in 5 locales.

## 6. Left to the builder

- Exact names, indexes, and CSV parsing and encodings.
- Whether batch resolution is an RPC or Python.
- Screen wording and layout within the UI rules.
- Batching inside the retry sweep.
- How existing `email_to` tests migrate. Behaviour for unconnected orgs must stay equivalent.
- The `organizations.slug` format and how clashes are handled.
- New brand-kit fields: `postal_address`, `privacy_url`, `timezone`.

## 7. Verification

**Unit tests:**
- Batch resolution excludes every non-subscribed status, suppression, sunset, holdout, other org and already-emailed contact.
- Batch size, daily limit, window deferral, cancel on stop.
- Headers, footer and per-person link tokens on every send.
- A forged unsubscribe token is rejected.
- Segment filters, including the language rule.
- The AI suggestion's input contains no personal data and its output contains only existing tags.
- Sandbox sends exactly one redirected email per batch.
- The safety pause thresholds.

**Integration tests (local Supabase):**
- RLS isolation of contacts, segments, settings and sends.
- Viewers can't read addresses.
- Import never re-subscribes and respects the cap.
- Double opt-in, one-click POST, self-erasure leaving only a hash.
- Webhook signature, idempotency, soft and hard bounces, unknown ids ignored.
- Vault keys are unreadable by authenticated SQL.

**Browser tests (Playwright, mocked):**
- the setup flow (sandbox and live), including webhook slot taken;
- import wizard, segment picker and Gate 1 suggestion;
- Gate 2 exclusions and "Send me a test";
- public join, confirmation and unsubscribe pages in 2 languages;
- 320 px layouts;
- viewers see no addresses.

**No real sends in tests.** The Resend client and API are faked. A live send happens only when the user connects a key and asks.

## 8. Rollout

- Unconnected orgs behave exactly as today (test inbox).
- Old campaigns keep `email_to`.
- Nothing changes for a brand until a manager connects Resend.

## 9. Resend's acceptable-use policy (checked 2026-10-26)

- **Marketing through the API is allowed** when:
  - every recipient **explicitly opted in**;
  - bulk email carries the company name and a valid address and says why the person gets it;
  - unsubscribe is frictionless and honoured within 7 days.
- **Cold outreach, purchased lists and scraped data are banned.**
- **Limits:** complaints must stay under **0.08%** and bounces under **4%**, or the account "may be shut down without warning".
- This design meets each point: D1, D8, the footer, one-click unsubscribe, double opt-in, the bounce rules and the safety pause.

## 10. Facts checked against Resend's docs

- `POST /api-keys` takes `permission: full_access | sending_access`, and a sending-only key can be restricted to one domain.
- A sending-only key can only send. It can't read emails, domains or webhooks, which is why D15 requires the webhook.
- `POST /webhooks` returns a `signing_secret`.
- The free plan has 1 webhook endpoint, 3 domains and 100 emails a day.
- Without a verified domain, only `onboarding@resend.dev` can send, and only to the account owner's address. Hence D28.
