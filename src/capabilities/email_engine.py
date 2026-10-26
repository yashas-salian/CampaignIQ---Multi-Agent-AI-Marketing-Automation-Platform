"""The email engine: everything a campaign round does to send its email.

send_round() is the one entry point (the graph's distribution_email node just
calls it). It checks the copy, picks who gets this round's email, builds one
email per person and sends them through the transport (Resend), under the
delivery ledger's at-most-once claim, and logs every recipient in the
per-recipient log (email_sends) by hash, never by address.

Two ways a round goes out:
  - the organisation connected its own Resend account (Settings → Email
    sending) and the campaign has an email audience: the next batch of the
    audience fixed at Gate 1, each person once per campaign, from the brand's
    own address with its key, a footer (why you got it, unsubscribe, postal
    address) and one-click unsubscribe headers. In sandbox mode (no verified
    domain) each batch is one labelled email to the Resend account owner.
  - not connected: the campaign's test list (the test inbox), as before.

The transport and the store are passed in so the whole round can run against
a fake Resend and an in-memory store in tests; production uses Resend and
Supabase.
"""
import base64
import html as html_lib
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from src.capabilities import email_copy, impact
from src.capabilities.brand import brand_kit_for_campaign, with_required_phrase
from src.capabilities.delivery import deliver
from src.capabilities.distribution import LINK_SLOT, personal_link, recipient_key, tracked_link, with_ad_image
from src.capabilities.experiments import split_recipients
from src.capabilities.guardrails import DISCLAIMERS, prepare_for_channel

log = logging.getLogger("capabilities.email_engine")

# Pause between two emails of one round: keeps a big list under the provider's rate limit.
SEND_PACING_SECONDS = 0.6  # Resend allows 2 requests a second by default
# A batch smaller than this says too little about the copy (unless that's everyone left).
MIN_BATCH = 20
# Share of the daily limit kept free for sign-up confirmation emails.
CONFIRMATION_RESERVE = 0.1
WAITING = "wait for the sending window or the daily limit"

# Per-person slots in a stored round payload, filled in when each email is built.
GREETING_SLOT = "__CIQ_GREETING__"
UNSUB_SLOT = "__CIQ_UNSUB__"
WHY_SLOT = "__CIQ_WHY__"
FIRST_NAME = "{first_name}"

Transport = Callable[..., str]


class SupabaseStore:
    """What the engine reads and writes, backed by Supabase (service role)."""

    @staticmethod
    def _db():
        from src.db.supabase_client import get_client

        return get_client()

    def record_sends(self, campaign_id: str, round_id: int, channel: str, rows: list[dict]) -> None:
        if not rows:
            return
        try:
            self._db().rpc("record_email_sends", {"p_campaign": campaign_id, "p_round": round_id,
                                                  "p_channel": channel, "p_rows": rows}).execute()
        except Exception as exc:  # the emails went out; a missing log row only shows as fewer "sent"
            log.warning("logging %d email sends for %s round %s failed: %s", len(rows), campaign_id, round_id, exc)

    def save_iteration(self, campaign_id: str, user_id: str, round_id: int, **fields) -> None:
        from src.db.supabase_client import upsert_iteration

        upsert_iteration(campaign_id, user_id, round_id, **fields)

    def experiment(self, campaign_id: str) -> dict | None:
        """The campaign's declared or running experiment, if any. A lookup
        failure sends the campaign normally rather than not at all (logged)."""
        try:
            exp = impact.experiment_for(campaign_id)
        except Exception as exc:
            log.warning("experiment lookup for %s failed, sending without it: %s", campaign_id, exc)
            return None
        return exp if exp and exp["status"] in ("declared", "running") else None

    def brand_kit(self, campaign_id: str):
        return brand_kit_for_campaign(campaign_id)

    def campaign_email(self, campaign_id: str) -> dict | None:
        rows = (self._db().table("campaigns").select("org_id,segment_id,max_rounds").eq("id", campaign_id).limit(1)
                .execute().data or [])
        return rows[0] if rows else None

    def sending_config(self, org_id: str | None) -> dict | None:
        """The organisation's connected Resend account (with its sending-only key), or None."""
        if not org_id:
            return None
        return self._db().rpc("email_sending_config", {"p_org": org_id}).execute().data

    def audience_progress(self, campaign_id: str) -> dict:
        return self._db().rpc("audience_progress", {"p_campaign": campaign_id}).execute().data

    def next_batch(self, campaign_id: str, size: int) -> list[dict]:
        return self._db().rpc("email_next_batch", {"p_campaign": campaign_id, "p_size": size}).execute().data or []

    def freeze(self, campaign_id: str) -> int:
        return self._db().rpc("freeze_campaign_audience", {"p_campaign": campaign_id}).execute().data or 0

    def audience_contacts(self, campaign_id: str) -> list[dict]:
        rows, start = [], 0
        while True:  # paged: an API response stops at 1000 rows
            page = (self._db().table("campaign_audience").select("contact_id,contacts(email)").eq("campaign_id", campaign_id)
                    .order("position").range(start, start + 999).execute().data or [])
            rows += [{"contact_id": r["contact_id"], "email": r["contacts"]["email"]} for r in page]
            if len(page) < 1000:
                return rows
            start += 1000

    def set_holdout(self, campaign_id: str, contact_ids: list[str]) -> None:
        self._db().rpc("set_audience_holdout", {"p_campaign": campaign_id, "p_contacts": contact_ids}).execute()

    def sent_today(self, org_id: str) -> int:
        return self._db().rpc("email_sent_today", {"p_org": org_id}).execute().data or 0

    def due_deferred(self, limit: int) -> list[dict]:
        return self._db().rpc("email_due_deferred", {"p_limit": limit}).execute().data or []

    def round_payload(self, campaign_id: str, round_number: int, channel: str) -> dict | None:
        rows = (self._db().table("deliveries").select("payload").eq("campaign_id", campaign_id).eq("round_number", round_number)
                .eq("channel", channel).limit(1).execute().data or [])
        return rows[0]["payload"] if rows and rows[0].get("payload") else None

    def signup_link_info(self, campaign_id: str) -> dict | None:
        return self._db().rpc("campaign_signup_link", {"p_campaign": campaign_id}).execute().data

    def contact_catalog(self, org_id: str) -> dict | None:
        return self._db().rpc("contact_catalog", {"p_org": org_id}).execute().data

    def segment_count(self, org_id: str, flt: dict, language: str | None) -> int:
        return self._db().rpc("segment_count", {"p_org": org_id, "p_filter": flt, "p_language": language}).execute().data or 0

    def save_suggestion(self, campaign_id: str, suggestion: dict) -> None:
        self._db().table("campaigns").update({"email_suggestion": suggestion}).eq("id", campaign_id).execute()

    def paused_unnotified(self) -> list[dict]:
        return (self._db().table("org_email_settings").select("org_id,paused_reason").not_.is_("paused_reason", "null")
                .is_("paused_notified_at", "null").execute().data or [])

    def mark_pause_notified(self, org_id: str) -> None:
        from datetime import datetime, timezone

        self._db().table("org_email_settings").update({"paused_notified_at": datetime.now(timezone.utc).isoformat()}).eq(
            "org_id", org_id).execute()


def _default_transport(to, subject, html, image_bytes=None, **kw) -> str:
    from src.tools.resend_client import send_email

    return send_email(to, subject, html, image_bytes, **kw)


# --- The round ---------------------------------------------------------------------------------


def send_round(state: dict, *, transport: Transport | None = None, store=None, now: datetime | None = None) -> dict:
    """Send this round's email. Returns {"email_id": <ledger ref>} and stores the
    refs on the round's iteration. Never raises for a provider problem: the
    ledger records it and retries."""
    transport = transport or _default_transport
    store = store or SupabaseStore()
    now = now or datetime.now(timezone.utc)
    kit = store.brand_kit(state["campaign_id"])
    body, blocked = _body(state, state["creative"], kit)
    if blocked:
        return _saved(store, state, email_id=f"dead: {blocked}")

    try:
        info = store.campaign_email(state["campaign_id"])
        config = store.sending_config((info or {}).get("org_id") or state.get("org_id")) if info else None
    except Exception as exc:  # a settings lookup failing must not send to the wrong people, nor crash the round
        log.warning("email settings for %s unavailable, not sending this round: %s", state["campaign_id"], exc)
        return _saved(store, state, email_id=f"failed: email settings unavailable ({type(exc).__name__})")
    if config:
        return _contacts_round(state, info, config, body, kit, transport=transport, store=store, now=now)

    experiment = store.experiment(state["campaign_id"])
    variant = state.get("creative_b")
    if experiment:
        units = impact.start(experiment, state["email_to"])
        people_a, people_b = _experiment_groups(units, bool(variant))
    else:
        list_a, list_b = split_recipients(state["email_to"], salt=state["campaign_id"]) if variant else (state["email_to"], [])
        people_a, people_b = _people(list_a), _people(list_b)
    return _send_groups(state, people_a, people_b, body, kit, experiment, transport=transport, store=store)


def _send_groups(state, people_a, people_b, body, kit, experiment, *, transport, store, contacts=None, now=None) -> dict:
    ctx = dict(transport=transport, store=store, experiment_id=experiment["id"] if experiment else None, contacts=contacts, now=now)
    variant = state.get("creative_b")
    email_id = (_send(state, "email", people_a, body, state["creative"], **ctx)
                if people_a or not experiment else "skipped: no treatment recipients")
    fields = {"email_id": email_id}
    if variant and people_b:
        body_b, blocked_b = _body(state, variant, kit)
        fields["email_id_b"] = f"dead: {blocked_b}" if blocked_b else _send(state, "email_b", people_b, body_b, variant, **ctx)
    return _saved(store, state, **fields)


def _experiment_groups(units: dict, ab: bool) -> tuple[list[dict], list[dict]]:
    """Treatment groups of a proof-of-impact experiment (the control is never emailed)."""
    group_a = [(a, u) for a, u in units.items() if u["arm"] == "treatment" or (u["arm"] == "treatment_b" and not ab)]
    group_b = [(a, u) for a, u in units.items() if u["arm"] == "treatment_b" and ab]
    as_people = lambda group: [{"to": a, "token": u["token"], "unit_hash": u["unit_hash"]} for a, u in group]  # noqa: E731
    return as_people(group_a), as_people(group_b)


def batch_size(remaining: int, rounds_left: int) -> int:
    """Spread what's left of the audience over the rounds left, never below MIN_BATCH."""
    if remaining <= MIN_BATCH:
        return remaining
    return max(math.ceil(remaining / max(rounds_left, 1)), MIN_BATCH)


def window_open(now: datetime, config: dict) -> bool:
    local = now.astimezone(ZoneInfo(config.get("timezone") or "UTC"))
    return int(config.get("send_window_start", 0)) <= local.hour < int(config.get("send_window_end", 24))


def next_send_time(now: datetime, config: dict, *, tomorrow: bool = False) -> datetime:
    """When a waiting email may go: the next moment inside the sending window,
    from now, or (over today's limit) from the start of the next UTC day."""
    t = now.astimezone(timezone.utc)
    if tomorrow:
        t = t.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if window_open(t, config):
        return t
    local = t.astimezone(ZoneInfo(config.get("timezone") or "UTC"))
    start = int(config.get("send_window_start", 0))
    day = local if local.hour < start else local + timedelta(days=1)
    return day.replace(hour=start, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def available_now(now: datetime, config: dict, sent_today: int) -> int:
    """How many campaign emails may go right now: none outside the window; else
    the daily limit, less a share kept for sign-up confirmations, less today's sends."""
    if not window_open(now, config):
        return 0
    limit = int(config.get("daily_limit") or 100)
    return max(limit - math.ceil(limit * CONFIRMATION_RESERVE) - int(sent_today), 0)


def _contacts_round(state: dict, info: dict, config: dict, body: str, kit, *, transport, store, now: datetime) -> dict:
    """A connected brand: the next batch of the campaign's fixed audience."""
    if not info.get("segment_id"):
        return _saved(store, state, email_id="skipped: no email audience chosen")
    if config.get("paused_reason"):
        return _saved(store, state, email_id=f"held: email is paused ({config['paused_reason']})")
    progress = store.audience_progress(state["campaign_id"])
    if not progress["total"] and freeze_audience(state["campaign_id"], store=store):
        progress = store.audience_progress(state["campaign_id"])  # Gate 1 didn't fix it (a hiccup there): now
    if progress["remaining"] <= 0:
        return _saved(store, state, email_id=f"skipped: email reached all {progress['emailed']} people")
    rounds_left = int(info.get("max_rounds") or 1) - int(state["round_id"]) + 1
    batch = store.next_batch(state["campaign_id"], batch_size(progress["remaining"], rounds_left))
    if not batch:
        return _saved(store, state, email_id=f"skipped: email reached all {progress['emailed']} people")

    by_email = {c["email"]: c for c in batch}

    def person(address: str, **extra) -> dict:
        c = by_email[address]
        return {"to": address, "unit_hash": extra.pop("unit_hash", c["recipient_hash"]), "contact_id": c["contact_id"],
                "first_name": c.get("first_name"), "unsub_token": c["unsub_token"], "click_token": c.get("click_token"),
                "consent_source": c.get("consent_source"), **extra}

    experiment = store.experiment(state["campaign_id"])
    if experiment:
        units = impact.start(experiment, list(by_email))
        groups = _experiment_groups({a: u for a, u in units.items() if a in by_email}, bool(state.get("creative_b")))
        people_a, people_b = ([person(p["to"], token=p["token"], unit_hash=p["unit_hash"]) for p in g] for g in groups)
    else:
        list_a, list_b = (split_recipients(list(by_email), salt=state["campaign_id"]) if state.get("creative_b")
                          else (list(by_email), []))
        people_a, people_b = [person(a) for a in list_a], [person(b) for b in list_b]
    # Inside the sending window and within the daily limit now; the rest waits, in batch order.
    org_id = info.get("org_id") or state.get("org_id")
    room = available_now(now, config, store.sent_today(org_id))
    later = {c["email"] for c in batch[room:]}
    if later:
        after = next_send_time(now, config, tomorrow=window_open(now, config)).isoformat()
        for p in people_a + people_b:
            if p["to"] in later:
                p["after"] = after
    contacts = {"org_id": org_id, "sandbox": config["mode"] == "sandbox", "language": state.get("target_language", "en")}
    return _send_groups(state, people_a, people_b, body, kit, experiment, transport=transport, store=store, contacts=contacts, now=now)


def _saved(store, state: dict, **fields) -> dict:
    store.save_iteration(state["campaign_id"], state["user_id"], state["round_id"], **fields)
    return {"email_id": fields["email_id"]}


def _people(addresses: list[str]) -> list[dict]:
    unique = dict.fromkeys(a.strip() for a in addresses if a and a.strip())
    return [{"to": a, "unit_hash": recipient_key(a)} for a in unique]


def _body(state: dict, creative, kit) -> tuple[str | None, str | None]:
    """The checked copy as email html (with the domain's disclaimer), or why it was blocked."""
    domain = state.get("domain_category", "other")
    text, blocked = prepare_for_channel(
        with_required_phrase(creative.copy_text, kit), "email", domain_category=domain, cta_url=state.get("cta_url"),
        banned_terms=kit.forbidden_words if kit else (),
    )
    if blocked:
        return None, blocked
    body = _render_html(text, state)
    disclaimer = DISCLAIMERS.get(domain)
    if disclaimer:
        body += f'<p style="font-size:12px;color:#666">{html_lib.escape(disclaimer)}</p>'
    return body, None


def _render_html(copy_text: str, state: dict) -> str:
    user_id = state.get("user_id")
    if state.get("use_email_template") and user_id:
        from src.db.supabase_client import get_template

        template = get_template(user_id, "email")
        if template and template.get("email_html"):
            # The stored template is a full layout with a "{{copy}}" placeholder.
            return template["email_html"].replace("{{copy}}", copy_text)
    return f"<p>{copy_text}</p>"


def _send(state: dict, channel: str, people: list[dict], html: str, creative, *, transport, store, experiment_id,
          contacts: dict | None = None, now: datetime | None = None) -> str:
    """One email per person under one ledger row per campaign/round/channel."""
    campaign_id, round_id, cta_url = state["campaign_id"], state["round_id"], state.get("cta_url")
    image = creative.image_bytes or None
    personal = bool(experiment_id or contacts)  # each person's own link: their experiment token and/or click token
    link = (LINK_SLOT if personal else tracked_link(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel)) if cta_url else None
    if link:
        html = f'{html}<p><a href="{link}">Learn more</a></p>'
    if image:
        html = with_ad_image(html, creative.headline or creative.copy_text[:120], link)
    payload = {"experiment_id": experiment_id, "per_recipient": people, "subject": state["idea"][:78], "html": html,
               "cta_url": cta_url if personal else None}
    if contacts:
        # A brand's own contacts: a greeting on top and the footer at the bottom, filled in per person.
        payload.update(contacts)
        payload["html"] = f"<p>{GREETING_SLOT}</p>{html}"
    if image:
        payload["image_base64"] = base64.b64encode(image).decode()
    waiting = [p for p in people if p.get("after")]
    if waiting:  # logged now, so progress shows them and the sweep sends them when they're due
        store.record_sends(campaign_id, round_id, channel, [
            {"recipient_hash": p["unit_hash"], "contact_id": p.get("contact_id"), "status": "deferred", "send_after": p["after"]}
            for p in waiting])
    return deliver(
        channel, campaign_id, round_id, payload,
        lambda: send_payload(campaign_id, round_id, channel, payload, image, transport=transport, store=store, now=now),
        describe=f"would email {len(people)} recipient(s) one by one: {payload['subject']!r}", user_id=state.get("user_id"),
    )


def unsubscribe_url(token: str) -> str:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/functions/v1/unsubscribe?t={token}"


def _personal_body(payload: dict, r: dict, config: dict | None, *, campaign_id: str, round_id: int, channel: str) -> str:
    body = payload["html"]
    if payload.get("cta_url") and (r.get("token") or r.get("click_token")):
        link = personal_link(payload["cta_url"], campaign_id=campaign_id, round_id=round_id, channel=channel, token=r.get("token"),
                             contact_token=r.get("click_token"))
        body = body.replace(LINK_SLOT, html_lib.escape(link, quote=True))
    if config is None:
        return body
    language = payload.get("language")
    body = (body.replace(GREETING_SLOT, email_copy.greeting(r.get("first_name"), language))
                .replace(FIRST_NAME, email_copy.name_or_fallback(r.get("first_name"), language)))
    footer = email_copy.footer_html(brand=config["brand_name"], postal_address=config.get("postal_address") or "",
                                    privacy_url=config.get("privacy_url"), language=language,
                                    unsubscribe_slot=html_lib.escape(unsubscribe_url(r["unsub_token"]), quote=True),
                                    why_slot=email_copy.why(r.get("consent_source"), config["brand_name"], language))
    return body + footer


def send_payload(campaign_id: str, round_id: int, channel: str, payload: dict, image_bytes: bytes | None, *,
                 transport: Transport | None = None, store=None, now: datetime | None = None) -> str:
    """Send a stored round payload, one email per recipient, each with its own
    idempotency key, so a retry after a partial failure never emails anyone
    twice. A failed recipient doesn't stop the others; if any failed, it raises
    at the end so the ledger schedules a retry. Every recipient is logged.

    A brand's own contacts go out with the brand's key (looked up now, never
    stored in the payload), the per-person greeting, footer and unsubscribe
    headers; in sandbox mode the batch is one labelled email to the owner."""
    transport = transport or _default_transport
    store = store or SupabaseStore()
    now = now or datetime.now(timezone.utc)
    # People waiting for the sending window or the daily limit go later, from the sweep.
    people = [r for r in payload["per_recipient"] if not r.get("after") or datetime.fromisoformat(r["after"]) <= now]
    waiting = len(payload["per_recipient"]) - len(people)
    if not people and waiting:
        return f"deferred: {waiting} emails {WAITING}"
    config = None
    if payload.get("org_id"):
        config = store.sending_config(payload["org_id"])
        if not config:
            raise RuntimeError("email sending is no longer connected for this organisation")
        if config.get("paused_reason"):
            raise RuntimeError(f"email is paused ({config['paused_reason']})")
    sender = {"api_key": config["api_key"], "from": config["from"], "reply_to": config.get("reply_to")} if config else None

    if payload.get("sandbox") and people:
        return _send_sandbox(campaign_id, round_id, channel, payload, image_bytes, config, sender, transport=transport, store=store)

    sent, log_rows, first_id, errors = [], [], None, []
    try:
        for i, r in enumerate(people):
            if i:
                time.sleep(SEND_PACING_SECONDS)
            body = _personal_body(payload, r, config, campaign_id=campaign_id, round_id=round_id, channel=channel)
            extra = {}
            if config:
                url = unsubscribe_url(r["unsub_token"])
                extra = {"sender": sender, "headers": {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}}
            row = {"recipient_hash": r["unit_hash"], "contact_id": r.get("contact_id")}
            try:
                email_id = transport([r["to"]], payload["subject"], body, image_bytes,
                                     idempotency_key=f"{campaign_id}:{round_id}:{channel}:{r['unit_hash'][:32]}", **extra)
            except Exception as exc:
                errors.append(exc)
                log_rows.append({**row, "status": "failed", "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
                continue
            first_id = first_id or email_id
            sent.append(r["unit_hash"])
            log_rows.append({**row, "status": "sent", "resend_id": email_id})
    finally:
        store.record_sends(campaign_id, round_id, channel, [_clean(x) for x in log_rows])
        if sent and payload.get("experiment_id"):  # whatever went out is an exposure, even if a later send failed
            impact.record_exposures(payload["experiment_id"], round_id, sent)
    if errors:
        raise RuntimeError(f"{len(errors)} of {len(people)} emails failed: {errors[0]}") from errors[0]
    return f"{len(sent)} emails ({first_id})" + (f", {waiting} {WAITING}" if waiting else "")


def _clean(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None}


def _send_sandbox(campaign_id, round_id, channel, payload, image_bytes, config, sender, *, transport, store) -> str:
    """Sandbox (no verified domain): Resend only delivers to the account owner,
    so the batch becomes one labelled email to them, built for the first person;
    everyone in the batch is logged as sent (sandbox) so the flows can be shown."""
    people = payload["per_recipient"]
    first = people[0]
    body = _personal_body(payload, first, config, campaign_id=campaign_id, round_id=round_id, channel=channel)
    url = unsubscribe_url(first["unsub_token"])
    email_id = transport([config["sandbox_to"]], f"[Sandbox: would have gone to {len(people)} people] {payload['subject']}", body,
                         image_bytes, idempotency_key=f"{campaign_id}:{round_id}:{channel}:sandbox", sender=sender,
                         headers={"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
    store.record_sends(campaign_id, round_id, channel, [
        {"recipient_hash": r["unit_hash"], "contact_id": r.get("contact_id"), "status": "sent", "resend_id": email_id, "sandbox": True}
        for r in people])
    if payload.get("experiment_id"):
        impact.record_exposures(payload["experiment_id"], round_id, [r["unit_hash"] for r in people])
    return f"sandbox: 1 email to the account owner for {len(people)} people ({email_id})"



# --- The sign-up link on campaign posts ---------------------------------------------------------


def signup_line(campaign_id: str, *, store=None) -> str | None:
    """"Join our list: <link>" for the campaign's posts, while the brand's email is
    connected and the campaign hasn't switched it off; the link carries the
    campaign, so sign-ups are credited to it. None otherwise (never raises)."""
    store = store or SupabaseStore()
    try:
        info = store.signup_link_info(campaign_id)
    except Exception as exc:
        log.warning("sign-up link for %s unavailable: %s", campaign_id, exc)
        return None
    if not info:
        return None
    base = os.environ.get("APP_BASE_URL", "https://campaign-iq-multi-agent-ai-marketin.vercel.app").rstrip("/")
    return f"{email_copy.words(info.get('language'))['join']} {base}/join/{info['slug']}?c={campaign_id}"


def with_signup_line(text: str, line: str | None, *, max_len: int | None = None) -> str:
    """The post with the sign-up line under it, if there is one and it fits."""
    if not line:
        return text
    combined = f"{text.rstrip()}\n\n{line}"
    return text if max_len is not None and len(combined) > max_len else combined


# --- The AI's suggested audience (Gate 1) -------------------------------------------------------


def _catalog_text(catalog: dict) -> str:
    """The catalogue as lines of names and counts: everything the model sees about the subscribers."""
    def group(key: str) -> str:
        return ", ".join(f"{g['name']} ({g['people']})" for g in catalog.get(key) or []) or "none"

    recent = catalog.get("purchased_within") or {}
    return (f"subscribed people: {catalog.get('subscribed', 0)}\n"
            f"tags: {group('tags')}\n"
            f"products bought: {group('products')}\n"
            f"countries: {group('countries')}\n"
            f"languages: {group('languages')}\n"
            f"bought in the last 30 days: {recent.get('30', 0)}, 90 days: {recent.get('90', 0)}, 365 days: {recent.get('365', 0)}, "
            f"never: {recent.get('never', 0)}")


def _valid_filter(raw: object, catalog: dict) -> dict:
    """Keep only what the catalogue has (in its own spelling) and sensible day counts; drop the rest."""
    if not isinstance(raw, dict):
        return {}
    known = {key: {g["name"].lower(): g["name"] for g in catalog.get(key) or []} for key in ("tags", "products", "countries")}
    out: dict = {}
    for key, group in (("tags_any", "tags"), ("tags_none", "tags"), ("product_any", "products"), ("country_any", "countries")):
        names = raw.get(key)
        if isinstance(names, list):
            kept = list(dict.fromkeys(known[group][n.strip().lower()] for n in names if isinstance(n, str) and n.strip().lower() in known[group]))
            if kept:
                out[key] = kept
    for key in ("purchased_within_days", "not_purchased_within_days"):
        days = raw.get(key)
        if isinstance(days, (int, float)) and 1 <= days <= 3650:
            out[key] = int(days)
    return out


def suggest_audience(campaign_id: str, org_id: str, idea: str, personas: list, language: str = "en", *, llm=None,
                     user_id: str | None = None, store=None) -> dict | None:
    """Suggest who gets the campaign email, from the personas and a catalogue of
    the brand's subscribers made only of group names and counts (never an
    address or one person's record). Only names in the catalogue survive. Stored
    on the campaign for Gate 1, where a person accepts or ignores it. Never raises."""
    from src.languages import language_name
    from src.llm_json import generate_json
    from src.prompts import PROMPTS
    from src.security.prompt_guard import fence

    store = store or SupabaseStore()
    try:
        catalog = store.contact_catalog(org_id)
        if not catalog or not catalog.get("subscribed"):
            return None
        if llm is None:
            from src.providers.registry import get_llm

            llm = get_llm(user_id)
        who = "\n".join(f"- {p.name}: {p.demographics}; {p.psychographics}; angle: {p.messaging_angle}" for p in personas)
        prompt, system = PROMPTS["email.audience"].render(
            idea=fence(idea, "user_idea"), personas=fence(who, "personas"), catalog=_catalog_text(catalog),
            language=language_name(language))
        parsed = generate_json(llm, prompt, system=system)
        flt = _valid_filter(parsed.get("filter") if isinstance(parsed, dict) else None, catalog)
        reason = str(parsed.get("reason") or "")[:300] if isinstance(parsed, dict) else ""
        suggestion = {"filter": flt, "reason": reason, "people": store.segment_count(org_id, flt, language)}
        store.save_suggestion(campaign_id, suggestion)
        return suggestion
    except Exception as exc:
        log.warning("audience suggestion for %s failed (Gate 1 goes on without it): %s", campaign_id, exc)
        return None


# --- Gate 1: fixing the audience ----------------------------------------------------------------


def freeze_audience(campaign_id: str, *, store=None) -> int:
    """Fix the campaign's email audience (Gate 1 approved). With a proof-of-impact
    experiment, the whole audience is assigned now and the control group is
    marked as the holdout, so no batch ever emails it. Returns the audience size."""
    store = store or SupabaseStore()
    size = store.freeze(campaign_id)
    experiment = store.experiment(campaign_id)
    if size and experiment:
        people = store.audience_contacts(campaign_id)
        units = impact.start(experiment, [p["email"] for p in people])
        control = {a for a, u in units.items() if u["arm"] == "control"}
        store.set_holdout(campaign_id, [p["contact_id"] for p in people if p["email"] in control])
    return size



# --- The hourly sweep ---------------------------------------------------------------------------


def sweep(*, store=None, transport: Transport | None = None, notify=None, now: datetime | None = None) -> dict:
    """Run from the hourly campaign loop: send waiting emails that are due, and
    tell managers about newly paused email. Never raises."""
    store = store or SupabaseStore()
    now = now or datetime.now(timezone.utc)
    if notify is None:
        from src.notifications import notify_email_paused as notify
    sent = 0
    try:
        sent = _send_due(store, transport or _default_transport, now)
    except Exception as exc:
        log.warning("sending waiting emails failed: %s", exc)
    told = 0
    try:
        for org in store.paused_unnotified():
            if notify(org["org_id"], org["paused_reason"]):
                store.mark_pause_notified(org["org_id"])
                told += 1
    except Exception as exc:
        log.warning("email pause notifications failed: %s", exc)
    return {"deferred_sent": sent, "pause_notices": told}


def _requeue(store, campaign_id, round_number, channel, rows: list[dict], *, after: datetime | None, error: str | None = None) -> None:
    """Put due rows back to wait until `after`, or cancel them (after=None)."""
    store.record_sends(campaign_id, round_number, channel, [
        {"recipient_hash": r["recipient_hash"], "contact_id": r.get("contact_id"),
         **({"status": "deferred", "send_after": after.isoformat()} if after else {"status": "cancelled", "error": error})}
        for r in rows])


def _send_due(store, transport: Transport, now: datetime) -> int:
    """Waiting emails whose time came. Each organisation's window and daily limit
    still apply (what doesn't fit waits again); each round's stored payload
    rebuilds the emails, so nobody's copy changes in the meantime."""
    groups: dict[tuple, list[dict]] = {}
    for d in store.due_deferred(500):
        groups.setdefault((d["campaign_id"], d["round_number"], d["channel"], d["org_id"]), []).append(d)
    room: dict[str, int] = {}
    configs: dict[str, dict | None] = {}
    total = 0
    for (campaign_id, round_number, channel, org_id), rows in groups.items():
        if org_id not in configs:
            configs[org_id] = store.sending_config(org_id)
            room[org_id] = available_now(now, configs[org_id], store.sent_today(org_id)) if configs[org_id] else 0
        config = configs[org_id]
        payload = store.round_payload(campaign_id, round_number, channel)
        if not config or not payload:
            _requeue(store, campaign_id, round_number, channel, rows, after=None, error="email no longer connected or the round expired")
            continue
        if config.get("paused_reason"):
            _requeue(store, campaign_id, round_number, channel, rows, after=now + timedelta(hours=1))
            continue
        take, wait = rows[:room[org_id]], rows[room[org_id]:]
        if wait:
            _requeue(store, campaign_id, round_number, channel, wait, after=next_send_time(now, config, tomorrow=window_open(now, config)))
        if not take:
            continue
        hashes = {r["recipient_hash"] for r in take}
        people = [{k: v for k, v in p.items() if k != "after"} for p in payload["per_recipient"] if p["unit_hash"] in hashes]
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        try:
            send_payload(campaign_id, round_number, channel, {**payload, "per_recipient": people}, image,
                         transport=transport, store=store, now=now)
        except Exception as exc:  # whoever failed waits an hour and is tried again
            log.warning("waiting emails for %s round %s failed: %s", campaign_id, round_number, exc)
            _requeue(store, campaign_id, round_number, channel, take, after=now + timedelta(hours=1))
        room[org_id] -= len(people)
        total += len(people)
    return total


def send_adhoc(campaign_id: str, round_id: int, to: list[str], subject: str, html: str, *, cta_url: str | None = None,
               transport: Transport | None = None, store=None) -> str:
    """A one-off send outside a campaign round (the MCP tool): one email per
    address, under the same ledger claim and per-recipient log."""
    if cta_url:
        html = f'{html}<p><a href="{tracked_link(cta_url, campaign_id=campaign_id, round_id=round_id, channel="email")}">Learn more</a></p>'
    people = _people(to)
    payload = {"experiment_id": None, "per_recipient": people, "subject": subject, "html": html, "cta_url": None}
    return deliver(
        "email", campaign_id, round_id, payload,
        lambda: send_payload(campaign_id, round_id, "email", payload, None, transport=transport, store=store),
        describe=f"would email {len(people)} recipient(s) one by one: {subject!r}",
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    print(f"Email engine sweep: {sweep()}")
