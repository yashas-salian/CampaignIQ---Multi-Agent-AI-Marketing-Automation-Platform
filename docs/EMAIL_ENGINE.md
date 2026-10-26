# Email engine: campaign email to a brand's own customers, legally

Campaign emails go **only to the brand's own customers and subscribers who opted in**, from **the brand's own Resend account**. Strangers are never found or scraped. A brand reaches new people through its posts on Bluesky, Mastodon and Reddit; each post ends with the brand's **sign-up link**, and people who confirm by email join the list.

Design and decisions: [docs/superpowers/specs/2026-10-26-email-engine-design.md](superpowers/specs/2026-10-26-email-engine-design.md).

```
contacts ──(CSV import · sign-up form + email confirmation · API)──▶ consent record per person
segment (saved filter) ──Gate 1──▶ audience fixed (holdout marked) ──each round──▶ next batch
batch ──window + daily limit──▶ one email per person, brand's key ──▶ Resend webhook ──▶ delivered / bounced / complained
                       └──▶ the rest waits (deferred) ──hourly sweep──▶ sent when due
```

## 1. Setting up a brand (Settings → Email sending)

**Requirements.** An owner or admin connects the brand's own Resend account. The free plan gives 3,000 emails a month and 100 a day. Before connecting, the brand kit needs a **postal address**: every marketing email shows it.

**Connecting:**
1. Paste a **full-access** key. The `email-setup` Edge Function then does three things with it:
   - lists the account's domains;
   - installs our webhook (`resend-webhook/{org}`) for delivered, bounced, complained and delayed events;
   - creates a **sending-only key restricted to the chosen domain**.
2. The full key is never stored. Only the sending-only key and the webhook's signing secret are kept, in **Supabase Vault**. The browser never sees either, and only the service role can read them.

**Modes:**
- **Live:** a domain verified in Resend. Email comes from, for example, `hello@yourbrand.com`.
- **Sandbox:** no verified domain yet. Resend only delivers to the account owner's own address, so each batch becomes **one email to that address**, labelled "[Sandbox: would have gone to N people]". All the flows still run: batches, logging, unsubscribe. Setup proves the owner's address with one test send.

**Refusals and settings:**
- If the account's webhook slot is taken (the free plan allows one), setup stops and says so. Without bounce and complaint reports we can't keep the brand under Resend's limits.
- Managers set the **daily limit** (default 100) and the **sending window** (default 09:00–20:00 in the brand's time zone).

Without a connected account, campaign email goes to the app's test inbox only, as before.

## 2. Contacts and consent (the Contacts page)

Each contact has:
- an email, names and a language;
- tags and purchase attributes;
- a status: `pending`, `subscribed`, `unsubscribed`, `bounced` or `complained`;
- a **consent record**: source, note, the exact wording they agreed to, when, and when confirmed.

Every change is in `contact_events`. Owners, admins and marketers see addresses; everyone else sees counts.

**How people get in:**
- **CSV import:** map the columns, say where people opted in, and tick the attestation. Invalid, duplicate, suppressed and over-the-limit rows are skipped and listed.
- **Sign-up form** `/join/{brand}`: double opt-in, always. The confirmation link expires after 7 days. Sign-ups are tagged `signed-up` (and `from:<campaign>` when they came through a campaign post). The form allows 5 tries an hour per address, and closes politely past 110% of the plan's contact limit.
- **API** `POST /v1/contacts`, with a `consent` object.

**The suppression list (`email_suppressions`, by hash):** anyone who unsubscribed, bounced, complained or was erased is on it, and no import or API call brings them back.
- Someone who unsubscribed can return **only** by confirming through the form.
- A complaint or an erasure is permanent.

**Inactivity:** a contact with no click or purchase in **24 months** is inactive and isn't emailed until they engage again.

**Plan limits:** 1,000 contacts on the free plan, unlimited on paid plans.

## 3. Who gets a campaign

**Segments:** saved filters over tags (any, all, none), purchase recency, products, countries, and the campaign's language (on by default).

**Choosing the audience at Gate 1:**
- The brand picks a segment at Gate 1.
- The AI may **suggest** one. It sees only group names and counts, never an address or a person's record. Anything not in the brand's catalogue is dropped. A person accepts the suggestion or ignores it.
- The **audience is fixed when Gate 1 is approved**, in a stable shuffled order. A proof-of-impact experiment's control group is drawn from the whole audience then and never emailed.

**Batches:**
- Each round emails the **next batch**: what's left, spread over the rounds left, never fewer than 20.
- **Nobody gets the same campaign twice.**
- Everyone is re-checked just before sending, so an unsubscribe between rounds counts.
- A/B variants split within the batch.

**Daily limit and sending window:** what doesn't fit waits (`deferred`), and the hourly sweep sends it when due. 10% of the limit is kept for sign-up confirmations. Stopping a campaign cancels what's waiting. A circuit-breaker hold keeps it waiting.

## 4. Every email

- **Sender:** the brand's own address and key.
- **Greeting:** "Hi {first name}," (or a fallback). A `{first_name}` placeholder in the copy also works.
- **Footer:**
  - why the person gets it (from their consent source);
  - an unsubscribe link;
  - the privacy link;
  - the brand's name and postal address;
  - a note that links are tracked.
- **Headers:** RFC 8058 one-click `List-Unsubscribe` + `List-Unsubscribe-Post`.
- **Links** carry the person's own click token (`k`), which marks them engaged. Their unsubscribe token never leaves the email.

**Unsubscribe page** (`/unsubscribe`, in the person's language, no app chrome):
- opening it never unsubscribes by itself (mail scanners open links);
- Gmail's one-click POST unsubscribes at once;
- the page offers "Resubscribe" (a new confirmation) and **"Also delete my details"** (erasure).

## 5. Bounces, complaints, the safety pause

The webhook (Svix-signed, checked with the organisation's own secret, each event counted once) records:
- **delivered**;
- **hard bounces:** suppressed at once;
- **soft bounces:** suppressed after 3 in a row;
- **complaints:** suppressed for good.

Events for the brand's other email are ignored.

**Safety pause:** Resend shuts accounts down at 0.08% complaints or 4% bounces. So once an organisation has sent 200 emails in 30 days, email **pauses** at 0.06% or 3%. Managers are told (hourly sweep), and an owner or admin resumes after looking.

**Rewards:** the email reward the bandit learns from is clicks over **delivered** (over sent until reports arrive). A round that only waited for the window isn't scored.

## 6. Privacy

- **Owners and admins** export everyone with their consent history (CSV), and **erase** a person. Erasing deletes them and their history, unlinks their past sends, keeps only the never-email-again hash, and is audited without the address.
- **Customers** erase themselves from the unsubscribe page.
- **API:** `DELETE /v1/contacts/{email}` does the same.

## 7. API

All routes are documented in [openapi.yaml](openapi.yaml).

| Call | Scope | What |
|---|---|---|
| `POST /v1/contacts` | write | Up to 1,000 contacts with a `consent` object (source, wording, note) |
| `GET /v1/contacts/counts` | read | By status, no addresses |
| `DELETE /v1/contacts/{email}` | write (owner/admin key) | Erase |
| `GET /v1/segments` | read | With people now |
| `PUT /v1/campaigns/{id}/email-audience` | write | `{segment_id}` until Gate 1 is approved |
| `POST /v1/conversions` | write | With `email`: also updates that contact's purchase history and engagement |

`email_to` on `POST /v1/campaigns` is refused (422) for organisations with email connected.

## 8. Where things are

| Part | Location |
|---|---|
| Sending a round, batches, window and limit, sweep, AI suggestion | `src/capabilities/email_engine.py` (`python -m src.capabilities.email_engine` runs the hourly sweep) |
| Greeting and footer in 5 languages | `src/capabilities/email_copy.py` |
| Database | migrations `20261027000100`–`20261027001200` (`email_sends`, contacts, settings, audience, events, waiting, sign-up, engagement, privacy, suggestion, API, results) |
| Edge Functions | `email-setup`, `resend-webhook`, `unsubscribe`, `join`, `email-test`; their logic is in `supabase/functions/_shared/*.ts`, tested with `node --test` |
| Pages | Contacts (and Segments), Settings → Email sending, Gate 1 and Gate 2 email audience; public `/join/{slug}`, `/confirm`, `/unsubscribe` |
| Environment | `APP_BASE_URL` (the website, for links in emails) and `PUBLIC_FUNCTIONS_URL` (optional: where Resend reaches the webhook) on the Edge Functions; `SUPABASE_URL` and `TRACK_CLICK_BASE_URL` on the worker |

## 9. Tests

| Suite | What it proves |
|---|---|
| `tests/integration/test_db_email_engine.py` | **Contacts:** consent records, imports never re-subscribing anyone, plan caps, who sees addresses. **Settings:** keys only in Vault, readable only by the worker. **Audience:** segments and counts; the audience fixed once; batches never repeating anyone; holdout; unsubscribe and erasure by token. **Events:** webhook events, soft and hard bounces, the safety pause. **Waiting and sign-up:** waiting sends, stop cancels; double opt-in, rate limits, cap. **The rest:** engagement and the sunset; export and erasure; the AI's catalogue having no personal data; tenant isolation throughout |
| `tests/unit/test_email_engine.py` | **Sending:** one email per person through a fake Resend; headers, footer, greeting, click tokens; sandbox redirect; batch sizes; window and limit deferral and the sweep; pause notices. **The AI:** the suggestion sees no personal data and invented groups are dropped. **Other:** the sign-up line on posts; test-inbox behaviour unchanged |
| `supabase/functions/_shared/*.test.ts` | **Setup:** never keeps the full key; sends sandbox proof; stops on a taken webhook slot. **Webhook:** Svix verification. **Public pages:** one-click unsubscribe, sign-up that never reveals who's on the list, test sends |
| `frontend/e2e/contacts.spec.ts`, `email-settings.spec.ts`, `email-audience.spec.ts` | **Contacts page:** import wizard, consent history, export and erase. **Settings:** connect live and sandbox, errors, preferences, pause and resume. **Segments and Gates:** Gate 1 picker and suggestion, Gate 2 batch and test. **Public pages:** sign-up, confirm, unsubscribe, resubscribe, self-erasure. **Layout:** phone layouts |
