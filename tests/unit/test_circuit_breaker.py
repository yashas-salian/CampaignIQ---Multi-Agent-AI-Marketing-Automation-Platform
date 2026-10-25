"""Circuit breaker (src/capabilities/circuit_breaker.py): the deterministic
checks, placing holds, the pre-send hook and the sweep. The database
enforcement (claim_delivery refusing held sends, races, resolving) is in
tests/integration/test_db_circuit_breaker.py."""
from datetime import datetime, timedelta, timezone

import pytest

from src.capabilities import circuit_breaker as cb
from src.capabilities import delivery

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
CID = "8adfba20-8dd9-4886-88b7-4fd861098196"


class TestChecks:
    def test_an_offer_expires_at_its_end_time(self):
        assert cb.offer_expired({"offer_ends_at": None}, NOW) is None
        assert cb.offer_expired({"offer_ends_at": (NOW + timedelta(hours=1)).isoformat()}, NOW) is None
        s = cb.offer_expired({"offer_ends_at": (NOW - timedelta(minutes=1)).isoformat()}, NOW)
        assert s.trigger == "EXPIRED_OFFER" and s.severity == "critical" and s.evidence["offer_ends_at"]

    def test_only_a_definitely_broken_link_trips_it(self):
        assert cb.destination_broken({"cta_url": None}, lambda u: None) is None
        assert cb.destination_broken({"cta_url": "https://x.io"}, lambda u: {"status": "unverified", "detail": "timeout"}) is None
        s = cb.destination_broken({"cta_url": "https://x.io"}, lambda u: {"status": "invalid", "detail": "404"})
        assert s.trigger == "INVALID_DESTINATION" and "404" in s.detail

    def test_hard_rules_only_not_judgement_calls(self):
        # A word banned after approval is a hard rule...
        s = cb.policy_broken("Cheap coffee, ready when you arrive.", banned_terms=["cheap"])
        assert s and s.trigger == "POLICY_VIOLATION"
        # ...an urgency phrase an approver may have accepted with a reason is not.
        assert cb.policy_broken("Order before the spots run out.") is None
        assert cb.policy_broken("") is None

    def test_approvals_lapse_when_the_quorum_no_longer_holds(self):
        votes = [{"user_id": "a", "decision": "approve"}, {"user_id": "b", "decision": "edit"}]
        assert cb.approvals_lapsed(votes, {"a": "approver", "b": "admin"}, 2) is None
        s = cb.approvals_lapsed(votes, {"a": "approver", "b": "viewer"}, 2)  # b was downgraded
        assert s.trigger == "REVOKED_APPROVAL" and s.evidence["lapsed_approvers"] == ["b"]
        assert cb.approvals_lapsed(votes, {"a": "approver"}, 1) is None  # one valid approval is enough here
        assert cb.approvals_lapsed([{"user_id": "a", "decision": "reject"}], {}, 1) is None

    def test_brand_risk_needs_two_separate_crisis_headlines_about_the_topic(self):
        kw = "order ahead coffee"
        one = ["Coffee chain faces lawsuit over order ahead app outage"]
        assert cb.brand_risk(kw, one) is None
        two = one + ["Order-ahead coffee apps hit by data breach, regulators investigate"]
        s = cb.brand_risk(kw, two)
        assert s.trigger == "BRAND_RISK" and len(s.evidence["headlines"]) == 2
        assert cb.brand_risk(kw, [one[0], one[0]]) is None  # the same headline twice isn't two sources
        assert cb.brand_risk(kw, ["Coffee prices rise", "New coffee shop opens downtown"]) is None  # no crisis


class FakeHolds:
    def __init__(self):
        self.rpcs, self.active = [], []

    def table(self, name):
        return _Q(self, name)

    def rpc(self, name, params):
        self.rpcs.append((name, params))
        if name == "place_hold":
            self.active.append(params["p_trigger"])
        return type("R", (), {"execute": lambda s: type("D", (), {"data": "hold-1"})()})()


class _Q:
    def __init__(self, db, name):
        self.db, self.name = db, name

    def __getattr__(self, attr):
        return lambda *a, **k: self

    def execute(self):
        if self.name == "campaign_holds":
            return type("R", (), {"data": [{"id": "h"}] if self.db.active else []})()
        return type("R", (), {"data": []})()


def test_a_hold_is_placed_once_and_notified_once(monkeypatch):
    db = FakeHolds()
    notes = []
    monkeypatch.setattr(cb, "_client", lambda: db)
    monkeypatch.setattr("src.notifications.notify_hold", lambda *a, **k: notes.append(a[1]))
    signal = cb.Signal("EXPIRED_OFFER", "ended")
    campaign = {"id": CID, "org_id": "o1"}
    assert cb.place(campaign, signal) == "hold-1"
    cb.place(campaign, signal)  # the next sweep sees the same condition
    assert [r[0] for r in db.rpcs] == ["place_hold", "place_hold"]  # the database keeps one active hold
    assert notes == ["EXPIRED_OFFER"]  # and people hear about it once


def test_gather_runs_the_live_checks_for_a_live_round(monkeypatch):
    monkeypatch.setattr(cb, "_live_round", lambda cid, rnd: {"copy_text": "Cheap coffee now.", "headline": "", "cta": ""})
    monkeypatch.setattr(cb, "_round_votes", lambda cid, rnd: [])
    monkeypatch.setattr("src.capabilities.brand.brand_kit_for_campaign",
                        lambda cid: type("K", (), {"forbidden_words": ["cheap"]})())
    campaign = {"id": CID, "org_id": "o1", "status": "awaiting_metrics", "current_round": 1, "idea": "Coffee",
                "cta_url": "https://x.io", "offer_ends_at": (NOW - timedelta(days=1)).isoformat()}
    triggers = {s.trigger for s in cb.gather(campaign, check=lambda u: {"status": "invalid", "detail": "404"}, now=NOW)}
    assert triggers == {"EXPIRED_OFFER", "INVALID_DESTINATION", "POLICY_VIOLATION"}


def test_a_campaign_that_isnt_live_is_left_alone(monkeypatch):
    monkeypatch.setattr("src.db.supabase_client.get_campaign", lambda cid: {"id": cid, "status": "completed"})
    assert cb.evaluate_campaign(CID) == []


def test_the_pre_send_check_is_cached_and_never_raises(monkeypatch):
    calls = []

    def evaluate(cid, **k):
        calls.append(cid)
        raise RuntimeError("db down")

    monkeypatch.setattr(cb, "evaluate_campaign", evaluate)
    cb._recent.clear()
    cb.check_before_dispatch(CID)
    cb.check_before_dispatch(CID)  # three channels in the same minute: one check
    assert calls == [CID]


class HeldLedger(delivery.DbLedger):
    """The database ledger's answer when claim_delivery() finds an active hold."""

    def __init__(self):
        pass

    def claim(self, *a):
        return "done", "held: EXPIRED_OFFER (The offer ended)"


def test_a_held_send_never_reaches_the_channel_and_isnt_counted_as_a_post(monkeypatch):
    """The dry-run scenario in docs/CIRCUIT_BREAKER.md: an expired offer stops a send cold."""
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setattr(delivery, "ledger", HeldLedger)
    checked = []
    monkeypatch.setattr(cb, "check_before_dispatch", lambda cid: checked.append(cid))
    result = delivery.deliver("bluesky", CID, 1, {"copy_text": "hi"}, lambda: pytest.fail("sent while held"),
                              describe="would post", user_id="u1")
    assert result.startswith("held: EXPIRED_OFFER") and checked == [CID]
    from src.capabilities.metrics import _is_real_post_ref

    assert delivery.is_failure(result) and not _is_real_post_ref(result)


def test_the_sweep_skips_paused_campaigns(monkeypatch, capsys):
    from src.scheduler import run_iteration

    monkeypatch.setattr(run_iteration, "get_campaign", lambda cid: {"id": cid, "status": "awaiting_metrics", "paused_at": "2026-10-26T10:00:00Z"})
    monkeypatch.setattr(run_iteration, "_resume_metrics_wait", lambda *a: pytest.fail("advanced a paused campaign"))
    run_iteration.process_campaign(None, CID)
    assert "paused by the circuit breaker" in capsys.readouterr().out
