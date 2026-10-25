# Brand reputation circuit breaker: stop a live campaign the moment it becomes unsafe

The decision engine (before Gate 1) and the crash test (before Gate 2) check a campaign **before** it goes out. Neither can see what changes **after** launch:
- the offer ends;
- the landing page dies;
- the brand bans a word;
- an approver leaves;
- the news turns.

The circuit breaker (`src/capabilities/circuit_breaker.py`) watches running campaigns. On a critical condition it places a **hold** that pauses the whole campaign, or one channel, until an owner or admin resumes it.

```
hourly sweep ─┐
pre-send check ├─▶ deterministic checks ─▶ place_hold() ─▶ campaign_holds (active)
market watch ─┘                                             │
person: emergency stop / revoke approval ───────────────────┤
                                                            ▼
              claim_delivery() refuses every send ──▶ delivery status 'held'
                                                            │
     owner/admin: resolve_hold(note) ──▶ held sends re-queued, re-checked before they go
```

## 1. Triggers

Every rule is a threshold, not an LLM.

| Trigger | Fires when | Not enough on its own |
|---|---|---|
| `EXPIRED_OFFER` | the campaign's `offer_ends_at` has passed | — |
| `INVALID_DESTINATION` | the CTA link **definitely** fails: no such host, 404 or 410 | a timeout or a 5xx (it could be a blip) |
| `POLICY_VIOLATION` | the live round's post, headline or button now breaks a **hard rule**, e.g. a word the brand kit banned after approval. Uses the crash test's `rules-v1` policy checks. | judgement calls an approver already accepted with a reason (urgency, unverified numbers) |
| `REVOKED_APPROVAL` | the round's Gate 2 approvals no longer reach the organisation's quorum (an approver was removed or downgraded), or a person revoked the approval | — |
| `BRAND_RISK` | crisis words (recall, lawsuit, boycott, data breach, outbreak…) next to the campaign's topic in **at least two separate** news headlines | one headline, or the same headline twice |
| `MANUAL_STOP` | an owner, admin or approver pulled the emergency stop, with a reason | — |

Each hold stores the evidence:
- the link and its error;
- the headlines;
- the lapsed approvers;
- the rule findings;
- `signal_at`, when the evidence was observed (the news fetch time, for example).

Severity is either `critical`, which pauses, or `warning`, which only notifies. The checks above place critical holds. The schema also supports warnings for softer signals later.

## 2. Where it checks

1. **The hourly sweep.** `python -m src.capabilities.circuit_breaker` is the first step of the campaign-loop sweep. It checks every live campaign, and one campaign's failure never stops the rest.
2. **Right before each send.** `check_before_dispatch()` in `delivery.py` runs before a delivery is claimed. It's cached for 5 minutes per campaign, so a round's three channels don't fetch the link three times. It never raises.
3. **The daily market watch.** It already fetches news for each campaign's topic, so it passes the headlines to `check_news()` for `BRAND_RISK`.
4. **Through the API:** `POST /v1/campaigns/{id}/circuit-breaker/evaluate` and the worker capability `circuit_breaker`.

## 3. Enforcement is in the database

The checks are best effort. The guarantee is `claim_delivery()`, which every send goes through:

- **No send while a critical hold is active.** The claim returns the verdict `held` with the note `held: TRIGGER (detail)`, and the delivery row is stored with status `held`. The channel is never called.
- **One channel or all.** A hold with a channel stops only that channel (`email_b` counts as email). A hold without one stops every channel.
- **No race.** `place_hold()` locks the campaign row `FOR UPDATE`. `claim_delivery()` takes a `FOR SHARE` lock on it before checking holds. A send that arrives while a pause is being written waits for it and then sees it, so a worker holding stale state can't slip past. The integration test `test_a_pause_racing_a_send_wins_once_it_commits` proves this with two real connections.
- **One active hold per (campaign, trigger, channel).** The next sweep finding the same condition updates the evidence instead of adding a row, and people are notified once.
- **The sweep skips paused campaigns.** `run_iteration` doesn't advance a campaign with `paused_at` set.
- **Held sends aren't posts.** They never count as published in metrics or the bandit.

**Already-published posts stay up.** The breaker stops *new* sends. Deleting or correcting a post that's already out is a separate action, and the UI says so.

## 4. Who can do what (database-enforced)

| Action | Function | Who |
|---|---|---|
| Place a hold | `place_hold()` | workers only (service role) |
| Emergency stop | `emergency_stop(campaign, reason)` | owner, admin, approver, with a reason of 10+ characters |
| Revoke the live approval | `revoke_approval(campaign, reason)` | owner, admin, approver, with a reason of 10+ characters |
| Resume / mark a false alarm | `resolve_hold(hold, note, false_alarm)` | **owner or admin only**, with a note of 10+ characters |
| Set the offer's end date | `set_offer_end(campaign, ends_at)` | anyone with the create or manage right |

Members can read holds, and nobody can edit them directly (RLS). Every pause, stop, revoke and resume is written to the audit log with its note, so it also reaches the webhooks.

**Resuming:**
- The campaign is un-paused only when no critical hold remains. Resolving one of two leaves it paused.
- Held deliveries go back to the retry queue (`failed`, due now).
- On their next attempt they pass through the pre-send check and `claim_delivery()` again, so if the condition is still true they're held again.

## 5. In the app

- **Paused panel:** on a paused campaign, it leads the page. It shows:
  - what tripped;
  - which channel;
  - when it was detected and how fresh the evidence is;
  - the evidence itself;
  - the suggested response.

  Owners and admins get the note box with **Resume sends** and **It was a false alarm**. Everyone else sees who can resume.
- **Safety controls:** the offer's end date, the emergency stop and revoke approval (each needs a reason), and the history of earlier holds with their notes.
- **Dashboard:** a **Paused** pill on the campaign card.
- **Notifications:** approvers get the trigger, the detail, how many sends are waiting and the suggested response (`notify_hold`).
- **API:** `GET /v1/campaigns/{id}/holds` returns `{ paused, paused_at, holds }`.

## 6. Dry-run scenario: an expired offer stops a send cold

This runs locally with no real posting (`DRY_RUN=true`) and no image generation.

1. Start the local stack (`supabase start`, `supabase migration up`) and make a campaign that's live (`awaiting_metrics`) with an offer that ended yesterday:
   ```sql
   update campaigns set offer_ends_at = now() - interval '1 day' where id = '<campaign>';
   ```
2. Run the sweep:
   ```
   python -m src.capabilities.circuit_breaker
   → Circuit breaker: 1 signal(s) across live campaigns.
   ```
   The campaign now has `paused_at` set, and `campaign_holds` has one active `EXPIRED_OFFER` hold whose evidence includes the end date.
3. Try a send. The next delivery attempt calls `claim_delivery()`, which returns `held: EXPIRED_OFFER (The offer ended on …)`. The delivery row's status is `held`, and the channel client is never called.
4. Open the campaign. The paused panel shows the hold. As the owner, extend the offer (Safety controls → Offer ends), then **Resume sends** with a note such as "Offer extended to 30 November". The held delivery goes back to the queue and passes on its next attempt.

The same path is covered without a database by `tests/unit/test_circuit_breaker.py::test_a_held_send_never_reaches_the_channel_and_isnt_counted_as_a_post`. Against the real database it is covered by `tests/integration/test_db_circuit_breaker.py`.

## 7. Tests

| Suite | What it proves |
|---|---|
| `tests/unit/test_circuit_breaker.py` (11) | each check's threshold (including what's *not* enough), placing and notifying once, the gather for a live round, the cached never-raising pre-send hook, a held send never reaching the channel and not counting as a post, the sweep skipping paused campaigns |
| `tests/integration/test_db_circuit_breaker.py` (9) | a critical hold pauses every send and is kept once; channel holds; warnings don't pause; only owners/admins resume and must say why; held sends re-queued; one of two holds resolved leaves it paused; stop/revoke rights and reasons; RLS; the pause-vs-send race |
| `frontend/e2e/circuit.spec.ts` (7 × desktop and phone) | the paused panel and its evidence; resume only for owners/admins; a warning and a false alarm; offer end date, emergency stop, revoke and history; viewers can't stop; the Dashboard pill; no sideways scroll at 320 px |
