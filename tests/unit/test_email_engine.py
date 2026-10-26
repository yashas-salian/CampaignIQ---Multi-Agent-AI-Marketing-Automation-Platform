"""The email engine at its one entry point, send_round(), with a fake Resend
(the transport) and a fake store: who gets an email, how each one is built,
and what is logged per recipient."""
import pytest

from src.capabilities import delivery, email_engine
from src.capabilities.distribution import recipient_key
from src.capabilities.experiments import split_recipients


class FakeTransport:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def __call__(self, to, subject, html, image_bytes=None, *, idempotency_key=None, **kw):
        if to[0] in self.fail_for:
            raise RuntimeError("rate limited")
        self.sent.append({"to": to, "subject": subject, "html": html, "key": idempotency_key, **kw})
        return f"re_{len(self.sent)}"


class FakeStore:
    """In-memory stand-in for the Supabase-backed store."""

    def __init__(self):
        self.sends, self.iterations = [], {}

    def record_sends(self, campaign_id, round_id, channel, rows):
        self.sends += [{"campaign_id": campaign_id, "round": round_id, "channel": channel, **r} for r in rows]

    def save_iteration(self, campaign_id, user_id, round_id, **fields):
        self.iterations.update(fields)

    def experiment(self, campaign_id):
        return None

    def brand_kit(self, campaign_id):
        return None

    def campaign_email(self, campaign_id):
        return None  # no row: an ad-hoc or legacy send

    def sending_config(self, org_id):
        return None

    def signup_link_info(self, campaign_id):
        return None


def creative(text="Fresh coffee, ready when you arrive.", headline="Coffee"):
    return type("C", (), {"copy_text": text, "image_bytes": b"", "headline": headline})()


@pytest.fixture(autouse=True)
def live_file_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("DELIVERY_LEDGER", "file")
    monkeypatch.setenv("DEDUP_STORE_PATH", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("TRACK_CLICK_BASE_URL", raising=False)
    monkeypatch.setattr(email_engine, "SEND_PACING_SECONDS", 0)
    monkeypatch.setattr(delivery, "IN_PROCESS_BACKOFF", (0, 0))


def state(**over):
    return {"campaign_id": "c1", "user_id": "u1", "round_id": 1, "domain_category": "other", "idea": "Coffee to go",
            "email_to": ["a@x.io", "b@x.io"], "creative": creative(), "creative_b": None, "cta_url": None, **over}


def test_each_listed_address_gets_its_own_email_with_its_own_key():
    transport, store = FakeTransport(), FakeStore()
    out = email_engine.send_round(state(), transport=transport, store=store)
    assert [s["to"] for s in transport.sent] == [["a@x.io"], ["b@x.io"]]
    assert transport.sent[0]["key"] != transport.sent[1]["key"]
    assert out == {"email_id": "2 emails (re_1)"} and store.iterations["email_id"] == "2 emails (re_1)"


def test_every_recipient_is_logged_without_their_address():
    transport, store = FakeTransport(fail_for={"b@x.io"}), FakeStore()
    email_engine.send_round(state(), transport=transport, store=store)
    by_status = {r["status"] for r in store.sends}
    assert by_status == {"sent", "failed"}
    assert all("@" not in str(r) for r in store.sends)
    sent = next(r for r in store.sends if r["status"] == "sent")
    assert sent["resend_id"] == "re_1" and len(sent["recipient_hash"]) == 64 and sent["channel"] == "email"


def test_an_ab_round_sends_each_half_its_own_variant():
    transport, store = FakeTransport(), FakeStore()
    to = ["d@x.io", "c@x.io", "b@x.io", "a@x.io"]
    email_engine.send_round(state(email_to=to, creative=creative("Copy A"), creative_b=creative("Copy B")),
                            transport=transport, store=store)
    half_a, half_b = split_recipients(to, salt="c1")  # the same split metrics use
    got_a = [s["to"][0] for s in transport.sent if "Copy A" in s["html"]]
    got_b = [s["to"][0] for s in transport.sent if "Copy B" in s["html"]]
    assert got_a == half_a and got_b == half_b
    assert set(store.iterations) == {"email_id", "email_id_b"}


def test_the_control_group_is_never_emailed(monkeypatch):
    units = {"a@x.io": {"arm": "treatment", "token": "1" * 32, "unit_hash": "ha"},
             "b@x.io": {"arm": "control", "token": "2" * 32, "unit_hash": "hb"},
             "c@x.io": {"arm": "treatment_b", "token": "3" * 32, "unit_hash": "hc"}}
    store = FakeStore()
    store.experiment = lambda cid: {"id": "e1", "status": "declared"}
    monkeypatch.setattr(email_engine.impact, "start", lambda exp, addresses: units)
    monkeypatch.setattr(email_engine.impact, "record_exposures", lambda *a: None)
    transport = FakeTransport()
    email_engine.send_round(state(email_to=list(units)), transport=transport, store=store)
    assert [s["to"][0] for s in transport.sent] == ["a@x.io", "c@x.io"]  # A/B off: both treatment groups, never b


def test_a_regulated_domain_email_carries_its_disclaimer():
    transport = FakeTransport()
    email_engine.send_round(state(domain_category="finance_fintech", idea="Round-up investing", email_to=["a@x.io"],
                                  creative=creative("Invest your spare change.")), transport=transport, store=FakeStore())
    assert "not financial advice" in transport.sent[0]["html"].lower()


def test_blocked_copy_is_never_sent():
    transport, store = FakeTransport(), FakeStore()
    out = email_engine.send_round(state(creative=creative("Win big at scam.xyz")), transport=transport, store=store)
    assert transport.sent == [] and out["email_id"].startswith("dead: blocked")


def test_the_idempotency_key_names_the_round_and_the_person_not_the_address():
    transport = FakeTransport()
    email_engine.send_round(state(campaign_id="c7", round_id=2, email_to=["a@x.io"]), transport=transport, store=FakeStore())
    assert transport.sent[0]["key"] == "c7:2:email:" + recipient_key("a@x.io")[:32]


def test_the_ad_is_embedded_on_top_and_links_to_the_cta():
    transport = FakeTransport()
    ad = type("C", (), {"copy_text": "Fresh coffee.", "image_bytes": b"jpg", "headline": 'Say "hi"'})()
    email_engine.send_round(state(email_to=["a@x.io"], creative=ad, cta_url="https://shop.io"), transport=transport, store=FakeStore())
    html = transport.sent[0]["html"]
    assert '<a href="https://shop.io"><img src="cid:ad-image"' in html and 'alt="Say &quot;hi&quot;"' in html
    assert html.index("cid:ad-image") < html.index("Fresh coffee")


def test_no_image_means_no_tag():
    transport = FakeTransport()
    email_engine.send_round(state(email_to=["a@x.io"]), transport=transport, store=FakeStore())
    assert "cid:" not in transport.sent[0]["html"]


def test_the_cta_is_click_tracked_when_configured(monkeypatch):
    monkeypatch.setenv("TRACK_CLICK_BASE_URL", "https://ref.supabase.co/functions/v1/track-click")
    transport = FakeTransport()
    email_engine.send_round(state(campaign_id="c3", round_id=2, email_to=["a@x.io"], cta_url="https://shop.io/a?b=1"),
                            transport=transport, store=FakeStore())
    assert "track-click?url=https%3A%2F%2Fshop.io%2Fa%3Fb%3D1&campaign_id=c3&round_id=2&channel=email" in transport.sent[0]["html"]


def test_experiment_emails_carry_each_persons_own_link_and_record_exposures(monkeypatch):
    exposures = []
    monkeypatch.setenv("TRACK_CLICK_BASE_URL", "https://x.supabase.co/functions/v1/track-click")
    monkeypatch.setattr(email_engine.impact, "record_exposures", lambda exp, rnd, hashes: exposures.append((exp, rnd, hashes)))
    payload = {"experiment_id": "e1", "subject": "Hi", "cta_url": "https://brew.example/?ref=ad",
               "html": f'<p>Coffee</p><p><a href="{email_engine.LINK_SLOT}">Learn more</a></p>',
               "per_recipient": [{"to": "a@x.io", "token": "a" * 32, "unit_hash": "h" * 64},
                                 {"to": "b@x.io", "token": "b" * 32, "unit_hash": "k" * 64}]}
    transport = FakeTransport()
    assert email_engine.send_payload("c1", 2, "email", payload, None, transport=transport, store=FakeStore()) == "2 emails (re_1)"
    assert "t=" + "a" * 32 in transport.sent[0]["html"] and "b" * 32 not in transport.sent[0]["html"]
    assert exposures == [("e1", 2, ["h" * 64, "k" * 64])]


def test_a_partial_failure_still_records_who_was_emailed(monkeypatch):
    exposures = []
    monkeypatch.setattr(email_engine.impact, "record_exposures", lambda exp, rnd, hashes: exposures.append(hashes))
    payload = {"experiment_id": "e1", "subject": "Hi", "cta_url": None, "html": "<p>x</p>",
               "per_recipient": [{"to": "a@x.io", "token": "a" * 32, "unit_hash": "h1"},
                                 {"to": "b@x.io", "token": "b" * 32, "unit_hash": "h2"},
                                 {"to": "c@x.io", "token": "c" * 32, "unit_hash": "h3"}]}
    with pytest.raises(RuntimeError, match="1 of 3 emails failed"):
        email_engine.send_payload("c1", 1, "email", payload, None, transport=FakeTransport(fail_for={"b@x.io"}), store=FakeStore())
    assert exposures == [["h1", "h3"]]  # one failure doesn't stop the others


def test_an_adhoc_send_goes_one_by_one():
    transport = FakeTransport()
    assert email_engine.send_adhoc("mcp-1", 1, ["a@x.io", "b@x.io"], "Hi", "<p>x</p>", transport=transport, store=FakeStore()) == "2 emails (re_1)"
    assert [s["to"] for s in transport.sent] == [["a@x.io"], ["b@x.io"]]


# --- A connected brand emailing its own contacts ---------------------------------------------------

LIVE = {"mode": "live", "api_key": "re_send_only", "from": "Brewline <hello@brewline.coffee>", "from_email": "hello@brewline.coffee",
        "reply_to": "help@brewline.coffee", "sandbox_to": None, "daily_limit": 100, "send_window_start": 0, "send_window_end": 24,
        "timezone": "UTC", "paused_reason": None, "brand_name": "Brewline", "postal_address": "12 Bean St, Pune 411001",
        "privacy_url": "https://brewline.coffee/privacy", "slug": "brewline"}


def contact(i, first_name="Ana", source="checkout"):
    return {"contact_id": f"k{i}", "email": f"p{i}@x.io", "first_name": first_name, "language": "en",
            "recipient_hash": f"{i:064x}", "unsub_token": f"{i:032x}", "consent_source": source, "click_token": f"{i + 100:032x}"}


class ContactsStore(FakeStore):
    """A connected organisation whose campaign has a fixed audience."""

    def __init__(self, audience, config=LIVE, segment_id="s1", max_rounds=3, emailed=0):
        super().__init__()
        self.audience, self.config, self.segment_id, self.max_rounds = list(audience), config, segment_id, max_rounds
        self.emailed, self.asked = emailed, []

    def sending_config(self, org_id):
        return self.config

    def campaign_email(self, campaign_id):
        return {"segment_id": self.segment_id, "max_rounds": self.max_rounds, "org_id": "o1"}

    def sent_today(self, org_id):
        return 0

    def audience_progress(self, campaign_id):
        taken = {r["contact_id"] for r in self.sends}
        left = [c for c in self.audience if c["contact_id"] not in taken]
        return {"total": len(self.audience), "emailed": len(taken), "remaining": len(left), "holdout": 0, "excluded": 0}

    def next_batch(self, campaign_id, size):
        self.asked.append(size)
        taken = {r["contact_id"] for r in self.sends}
        return [c for c in self.audience if c["contact_id"] not in taken][:size]


def connected_state(**over):
    return state(org_id="o1", email_to=[], **over)


def test_a_connected_brand_emails_the_next_batch_of_its_own_contacts_through_its_own_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co")
    store, transport = ContactsStore([contact(i) for i in range(3)]), FakeTransport()
    out = email_engine.send_round(connected_state(), transport=transport, store=store)
    assert [s["to"] for s in transport.sent] == [["p0@x.io"], ["p1@x.io"], ["p2@x.io"]]
    sent = transport.sent[0]
    assert sent["sender"] == {"api_key": "re_send_only", "from": "Brewline <hello@brewline.coffee>", "reply_to": "help@brewline.coffee"}
    unsub = f"https://ref.supabase.co/functions/v1/unsubscribe?t={0:032x}"
    assert sent["headers"] == {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    html = sent["html"]
    assert f'href="{unsub}"' in html and "12 Bean St, Pune 411001" in html and "Brewline" in html
    assert "when you bought from Brewline" in html and "tracked" in html
    assert {r["contact_id"] for r in store.sends} == {"k0", "k1", "k2"} and out["email_id"] == "3 emails (re_1)"


def test_every_email_greets_its_own_person():
    store, transport = ContactsStore([contact(0, "Ana"), contact(1, None)]), FakeTransport()
    email_engine.send_round(connected_state(creative=creative("{first_name}, your coffee is ready.")), transport=transport, store=store)
    assert "Ana, your coffee is ready." in transport.sent[0]["html"]
    assert "Hi there, your coffee is ready." in transport.sent[1]["html"]
    assert "{first_name}" not in transport.sent[1]["html"]


def test_batches_spread_the_audience_over_the_rounds_never_below_twenty():
    store = ContactsStore([contact(i) for i in range(90)], max_rounds=3)
    email_engine.send_round(connected_state(round_id=1), transport=FakeTransport(), store=store)
    assert store.asked == [30]  # 90 people over 3 rounds
    store = ContactsStore([contact(i) for i in range(30)], max_rounds=10)
    email_engine.send_round(connected_state(round_id=1), transport=FakeTransport(), store=store)
    assert store.asked == [20]  # 3 a round would say nothing about the copy
    store = ContactsStore([contact(i) for i in range(12)], max_rounds=10)
    email_engine.send_round(connected_state(round_id=1), transport=FakeTransport(), store=store)
    assert store.asked == [12]


def test_nobody_gets_the_same_campaign_twice():
    store, transport = ContactsStore([contact(i) for i in range(25)], max_rounds=2), FakeTransport()
    email_engine.send_round(connected_state(round_id=1), transport=transport, store=store)
    email_engine.send_round(connected_state(round_id=2), transport=transport, store=store)
    addresses = [s["to"][0] for s in transport.sent]
    assert len(addresses) == 25 and len(set(addresses)) == 25


def test_when_everyone_was_reached_email_is_done_for_the_campaign():
    store, transport = ContactsStore([contact(0)]), FakeTransport()
    store.sends.append({"contact_id": "k0", "status": "sent"})
    out = email_engine.send_round(connected_state(round_id=2), transport=transport, store=store)
    assert transport.sent == [] and out["email_id"] == "skipped: email reached all 1 people"


def test_a_connected_brand_without_an_audience_sends_nothing():
    store, transport = ContactsStore([contact(0)], segment_id=None), FakeTransport()
    out = email_engine.send_round(connected_state(), transport=transport, store=store)
    assert transport.sent == [] and out["email_id"] == "skipped: no email audience chosen"


def test_a_paused_brand_sends_nothing():
    store, transport = ContactsStore([contact(0)], config={**LIVE, "paused_reason": "complaint rate 0.07%"}), FakeTransport()
    out = email_engine.send_round(connected_state(), transport=transport, store=store)
    assert transport.sent == [] and out["email_id"] == "held: email is paused (complaint rate 0.07%)"


def test_sandbox_sends_one_labelled_email_to_the_account_owner_and_logs_the_batch():
    sandbox = {**LIVE, "mode": "sandbox", "from": "Brewline <onboarding@resend.dev>", "sandbox_to": "ava@example.com"}
    store, transport = ContactsStore([contact(i) for i in range(3)], config=sandbox), FakeTransport()
    email_engine.send_round(connected_state(), transport=transport, store=store)
    assert len(transport.sent) == 1 and transport.sent[0]["to"] == ["ava@example.com"]
    assert transport.sent[0]["subject"].startswith("[Sandbox: would have gone to 3 people]")
    assert {r["contact_id"] for r in store.sends} == {"k0", "k1", "k2"} and all(r["sandbox"] for r in store.sends)


def test_an_ab_round_splits_the_batch():
    store, transport = ContactsStore([contact(i) for i in range(4)]), FakeTransport()
    email_engine.send_round(connected_state(creative=creative("Copy A"), creative_b=creative("Copy B")), transport=transport, store=store)
    a = {s["to"][0] for s in transport.sent if "Copy A" in s["html"]}
    b = {s["to"][0] for s in transport.sent if "Copy B" in s["html"]}
    assert a and b and not a & b and len(a | b) == 4
    assert {r["channel"] for r in store.sends} == {"email", "email_b"}


def test_a_retry_rebuilds_each_persons_email_with_the_brands_key():
    store, transport = ContactsStore([contact(0)]), FakeTransport(fail_for={"p0@x.io"})
    email_engine.send_round(connected_state(), transport=transport, store=store)
    payload = None
    import json
    from pathlib import Path
    import os
    ledger = json.loads(Path(os.environ["DEDUP_STORE_PATH"]).read_text())
    payload = ledger["c1:1:email"]["payload"]
    assert "p0@x.io" in json.dumps(payload) and "re_send_only" not in json.dumps(payload)  # the key is never stored
    ok = FakeTransport()
    assert email_engine.send_payload("c1", 1, "email", payload, None, transport=ok, store=store) == "1 emails (re_1)"
    assert ok.sent[0]["sender"]["api_key"] == "re_send_only" and "Ana" in ok.sent[0]["html"]


def test_freezing_the_audience_marks_the_experiments_control_group(monkeypatch):
    marked = {}

    class Store(ContactsStore):
        def freeze(self, campaign_id):
            return 3

        def audience_contacts(self, campaign_id):
            return [{"contact_id": f"k{i}", "email": f"p{i}@x.io"} for i in range(3)]

        def set_holdout(self, campaign_id, ids):
            marked["ids"] = ids

        def experiment(self, campaign_id):
            return {"id": "e1", "status": "declared"}

    arms = {"p0@x.io": "control", "p1@x.io": "treatment", "p2@x.io": "treatment"}
    monkeypatch.setattr(email_engine.impact, "start", lambda exp, addresses: {a: {"arm": arms[a], "token": "t", "unit_hash": a} for a in addresses})
    assert email_engine.freeze_audience("c1", store=Store([])) == 3
    assert marked["ids"] == ["k0"]


def test_a_settings_lookup_failure_sends_nothing_and_keeps_the_round_going():
    class Broken(FakeStore):
        def campaign_email(self, campaign_id):
            raise ConnectionError("db down")

    transport, store = FakeTransport(), Broken()
    out = email_engine.send_round(state(), transport=transport, store=store)
    assert transport.sent == [] and out["email_id"].startswith("failed: email settings unavailable")


def test_the_resend_client_sends_with_the_brands_key_and_headers(monkeypatch):
    from src.tools import resend_client

    calls = []
    monkeypatch.setenv("RESEND_API_KEY", "re_app")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "app@x.io")
    monkeypatch.setattr(resend_client.resend.Emails, "send", lambda params, *opts: calls.append((resend_client.resend.api_key, params)) or {"id": "e1"})
    resend_client.send_email(["a@x.io"], "Hi", "<p>x</p>", sender={"api_key": "re_brand", "from": "B <h@b.io>", "reply_to": "r@b.io"},
                             headers={"List-Unsubscribe": "<https://u>"})
    resend_client.send_email(["a@x.io"], "Hi", "<p>x</p>")
    (key1, p1), (key2, p2) = calls
    assert key1 == "re_brand" and p1["from"] == "B <h@b.io>" and p1["reply_to"] == "r@b.io" and p1["headers"] == {"List-Unsubscribe": "<https://u>"}
    assert key2 == "re_app" and p2["from"] == "app@x.io" and "headers" not in p2 and "reply_to" not in p2


def test_an_audience_gate_1_failed_to_fix_is_fixed_by_the_first_round():
    class Unfrozen(ContactsStore):
        def __init__(self, audience):
            super().__init__([])
            self.later = audience

        def freeze(self, campaign_id):
            self.audience = self.later
            return len(self.audience)

    store, transport = Unfrozen([contact(0), contact(1)]), FakeTransport()
    email_engine.send_round(connected_state(), transport=transport, store=store)
    assert [s["to"][0] for s in transport.sent] == ["p0@x.io", "p1@x.io"]


def test_the_sweep_tells_managers_once_about_paused_email():
    class Store(FakeStore):
        def __init__(self):
            super().__init__()
            self.paused = [{"org_id": "o1", "paused_reason": "complaint rate 0.07%"}, {"org_id": "o2", "paused_reason": "bounce rate 3.1%"}]
            self.marked = []

        def paused_unnotified(self):
            return [p for p in self.paused if p["org_id"] not in self.marked]

        def mark_pause_notified(self, org_id):
            self.marked.append(org_id)

        def due_deferred(self, limit):
            return []

    told = []
    store = Store()
    notify = lambda org, reason: told.append((org, reason)) or org == "o1"  # o2's notice fails: tried again next hour  # noqa: E731
    assert email_engine.sweep(store=store, notify=notify) == {"deferred_sent": 0, "pause_notices": 1}
    assert store.marked == ["o1"]
    assert email_engine.sweep(store=store, notify=notify) == {"deferred_sent": 0, "pause_notices": 0} and told[-1] == ("o2", "bounce rate 3.1%")


# --- The daily limit and the sending window -----------------------------------------------------

from datetime import datetime, timezone  # noqa: E402

IST = {**LIVE, "timezone": "Asia/Kolkata", "send_window_start": 9, "send_window_end": 20}


class LimitedStore(ContactsStore):
    def __init__(self, audience, config=IST, sent_today=0, **kw):
        super().__init__(audience, config=config, **kw)
        self.today = sent_today

    def sent_today(self, org_id):
        return self.today + sum(1 for r in self.sends if r["status"] == "sent")


def test_outside_the_sending_window_the_batch_waits_for_it_to_open():
    store, transport = LimitedStore([contact(i) for i in range(3)]), FakeTransport()
    late = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)  # 22:30 in India: after 20:00
    out = email_engine.send_round(connected_state(), transport=transport, store=store, now=late)
    assert transport.sent == []
    assert out["email_id"] == "deferred: 3 emails wait for the sending window or the daily limit"
    waiting = [r for r in store.sends if r["status"] == "deferred"]
    assert len(waiting) == 3 and {r["send_after"] for r in waiting} == {"2026-10-27T03:30:00+00:00"}  # 09:00 IST


def test_the_daily_limit_sends_what_fits_and_the_rest_waits_for_tomorrow():
    config = {**IST, "daily_limit": 10}
    store, transport = LimitedStore([contact(i) for i in range(8)], config=config, sent_today=4), FakeTransport()
    noon = datetime(2026, 10, 26, 6, 30, tzinfo=timezone.utc)  # 12:00 in India
    out = email_engine.send_round(connected_state(), transport=transport, store=store, now=noon)
    assert len(transport.sent) == 5  # 10 a day, 4 already sent, 1 kept for sign-up confirmations
    waiting = [r for r in store.sends if r["status"] == "deferred"]
    assert len(waiting) == 3 and {r["send_after"] for r in waiting} == {"2026-10-27T03:30:00+00:00"}  # tomorrow, once the window opens
    assert out["email_id"].startswith("5 emails (re_1)") and out["email_id"].endswith("3 wait for the sending window or the daily limit")


def test_the_sweep_sends_waiting_emails_once_they_are_due():
    store, transport = LimitedStore([contact(i) for i in range(3)]), FakeTransport()
    late = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)
    email_engine.send_round(connected_state(), transport=transport, store=store, now=late)
    import json
    import os
    from pathlib import Path

    payload = json.loads(Path(os.environ["DEDUP_STORE_PATH"]).read_text())["c1:1:email"]["payload"]
    store.round_payload = lambda cid, rnd, ch: payload
    store.due_deferred = lambda limit: [{"campaign_id": "c1", "round_number": 1, "channel": "email", "org_id": "o1",
                                         "recipient_hash": r["recipient_hash"], "contact_id": r["contact_id"]}
                                        for r in store.sends if r["status"] == "deferred"]
    morning = datetime(2026, 10, 27, 4, 0, tzinfo=timezone.utc)  # 09:30 in India
    result = email_engine.sweep(store=store, transport=transport, now=morning, notify=lambda *a: True)
    assert result["deferred_sent"] == 3 and len(transport.sent) == 3
    assert {s["to"][0] for s in transport.sent} == {"p0@x.io", "p1@x.io", "p2@x.io"}


def test_the_sweep_puts_emails_back_when_the_window_is_closed():
    store, transport = LimitedStore([contact(0)]), FakeTransport()
    store.round_payload = lambda cid, rnd, ch: {"per_recipient": [], "subject": "x", "html": "x", "org_id": "o1"}
    store.due_deferred = lambda limit: [{"campaign_id": "c1", "round_number": 1, "channel": "email", "org_id": "o1",
                                         "recipient_hash": f"{0:064x}", "contact_id": "k0"}]
    night = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)  # 23:30 in India
    email_engine.sweep(store=store, transport=transport, now=night, notify=lambda *a: True)
    assert transport.sent == [] and store.sends[-1]["status"] == "deferred"
    assert store.sends[-1]["send_after"] == "2026-10-27T03:30:00+00:00"


def test_a_round_that_only_waits_is_not_measured_as_zero():
    from src.capabilities.metrics import _is_real_post_ref

    assert not _is_real_post_ref("deferred: 3 emails wait for the sending window or the daily limit")
    assert _is_real_post_ref("5 emails (re_1), 3 wait for the sending window or the daily limit")


# --- The sign-up link on campaign posts ---------------------------------------------------------


def test_posts_get_the_brands_sign_up_link_carrying_the_campaign(monkeypatch):
    monkeypatch.setenv("APP_BASE_URL", "https://campaigniq.app/")

    class Store(FakeStore):
        def signup_link_info(self, campaign_id):
            return {"slug": "brewline", "language": "fr"}

    line = email_engine.signup_line("c1", store=Store())
    assert line == "Inscrivez-vous : https://campaigniq.app/join/brewline?c=c1"
    assert email_engine.with_signup_line("Fresh coffee.", line, max_len=300) == f"Fresh coffee.\n\n{line}"
    assert email_engine.with_signup_line("x" * 280, line, max_len=300) == "x" * 280  # doesn't fit: the post stays as it was
    assert email_engine.signup_line("c1", store=FakeStore()) is None  # not connected, or switched off for this campaign


def test_the_bluesky_post_ends_with_the_sign_up_link(monkeypatch):
    from src.graph.nodes import distribution_bluesky as node

    posted = {}
    monkeypatch.setattr(node, "brand_kit_for_campaign", lambda cid: None)
    monkeypatch.setattr(node, "signup_line", lambda cid: "Join our list: https://campaigniq.app/join/brewline?c=c1")
    monkeypatch.setattr(node, "post_bluesky", lambda cid, rid, text, **k: posted.setdefault("text", text) and "at://1")
    monkeypatch.setattr(node, "upsert_iteration", lambda *a, **k: None)
    node.distribution_bluesky_node(state(creative=creative("Fresh coffee, ready when you arrive.")))
    assert posted["text"].endswith("Join our list: https://campaigniq.app/join/brewline?c=c1")


def test_each_persons_link_carries_their_own_click_token_but_never_their_unsubscribe_token(monkeypatch):
    monkeypatch.setenv("TRACK_CLICK_BASE_URL", "https://ref.supabase.co/functions/v1/track-click")
    store, transport = ContactsStore([contact(0), contact(1)]), FakeTransport()
    email_engine.send_round(connected_state(cta_url="https://brew.example/order"), transport=transport, store=store)
    first, second = (s["html"] for s in transport.sent)
    assert f"k={100:032x}" in first and f"k={101:032x}" in second and f"k={100:032x}" not in second
    assert "track-click?url=https%3A%2F%2Fbrew.example%2Forder&amp;campaign_id=c1&amp;round_id=1&amp;channel=email" in first
    link = first[first.index("track-click"):first.index('"', first.index("track-click"))]
    assert f"{0:032x}" not in link  # the unsubscribe token stays out of the tracked link


def test_without_click_tracking_the_link_goes_straight_to_the_brand():
    store, transport = ContactsStore([contact(0)]), FakeTransport()
    email_engine.send_round(connected_state(cta_url="https://brew.example/order"), transport=transport, store=store)
    assert 'href="https://brew.example/order"' in transport.sent[0]["html"] and "k=" not in transport.sent[0]["html"]


# --- The AI's suggested audience (Gate 1) -------------------------------------------------------

CATALOG = {"subscribed": 240, "tags": [{"name": "coffee", "people": 180}, {"name": "commuter", "people": 90}, {"name": "tea", "people": 40}],
           "products": [{"name": "cold brew", "people": 70}], "countries": [{"name": "india", "people": 200}],
           "languages": [{"name": "en", "people": 230}], "purchased_within": {"30": 50, "90": 120, "365": 200, "never": 40}}


class SuggestStore(FakeStore):
    def __init__(self, catalog=CATALOG, people=120):
        super().__init__()
        self.catalog, self.people, self.saved = catalog, people, None

    def contact_catalog(self, org_id):
        return self.catalog

    def segment_count(self, org_id, flt, language):
        self.counted = flt
        return self.people

    def save_suggestion(self, campaign_id, suggestion):
        self.saved = suggestion


PERSONAS = [type("P", (), {"name": "Rushed commuter", "demographics": "25-34, city office worker", "psychographics": "values time",
                           "messaging_angle": "skip the queue"})()]


def test_the_ai_suggests_an_audience_from_names_and_counts_never_personal_data(fake_llm):
    llm = fake_llm('{"filter": {"tags_any": ["coffee", "commuter"], "purchased_within_days": 90}, "reason": "Recent coffee buyers who commute."}')
    store = SuggestStore()
    out = email_engine.suggest_audience("c1", "o1", "Order-ahead coffee", PERSONAS, "en", llm=llm, store=store)
    assert out == {"filter": {"tags_any": ["coffee", "commuter"], "purchased_within_days": 90}, "reason": "Recent coffee buyers who commute.",
                   "people": 120}
    assert store.saved == out
    prompt = llm.prompts[0]
    assert "coffee (180)" in prompt and "Rushed commuter" in prompt and "@" not in prompt


def test_anything_not_in_the_catalogue_is_dropped(fake_llm):
    llm = fake_llm('{"filter": {"tags_any": ["coffee", "vip-gold"], "product_any": ["Cold Brew", "jetpack"], "country_any": ["Mars"], '
                   '"purchased_within_days": 99999, "email": "x@y.z"}, "reason": "ok"}')
    out = email_engine.suggest_audience("c1", "o1", "Coffee", PERSONAS, "en", llm=llm, store=SuggestStore())
    assert out["filter"] == {"tags_any": ["coffee"], "product_any": ["cold brew"]}


def test_no_contacts_means_no_suggestion_and_no_ai_call(fake_llm):
    llm = fake_llm("{}")
    assert email_engine.suggest_audience("c1", "o1", "Coffee", PERSONAS, "en", llm=llm, store=SuggestStore(catalog={"subscribed": 0})) is None
    assert llm.prompts == []


def test_a_broken_ai_answer_never_stops_gate_1(fake_llm):
    llm = fake_llm("not json at all")
    assert email_engine.suggest_audience("c1", "o1", "Coffee", PERSONAS, "en", llm=llm, store=SuggestStore()) is None


def test_the_audience_step_suggests_the_email_audience_once_personas_exist(monkeypatch):
    from src.graph.nodes import audience as node

    asked = {}
    monkeypatch.setattr(node, "generate_personas", lambda *a, **k: PERSONAS)
    monkeypatch.setattr(node, "insert_personas", lambda *a, **k: None)
    monkeypatch.setattr(node, "recall", lambda ctx: type("R", (), {"section": ""})())
    monkeypatch.setattr(node, "context_from_state", lambda s: None)
    monkeypatch.setattr(node, "suggest_audience", lambda cid, org, idea, personas, lang, **k: asked.update(cid=cid, org=org, personas=personas))
    node.audience_node({"campaign_id": "c1", "user_id": "u1", "org_id": "o1", "idea": "Coffee", "feasibility": None})
    assert asked == {"cid": "c1", "org": "o1", "personas": PERSONAS}
