from datetime import datetime, timedelta, timezone

import pytest

from src import notifications

APPROVERS = [
    {"user_id": "o", "email": "owner@acme.io", "email_on": True},
    {"user_id": "a", "email": "approver@acme.io", "email_on": True},
    {"user_id": "q", "email": "quiet@acme.io", "email_on": False},  # turned email off
]
MANAGERS = [{"user_id": "o", "email": "owner@acme.io", "email_on": True}]
CAMPAIGN = {"id": "c1", "idea": "Spice kits from home cooks", "org_id": "org", "user_id": "o"}


@pytest.fixture
def sent(monkeypatch):
    """Every channel recorded; the campaign, settings and recipients faked."""
    log = {"slack": [], "email": [], "inbox": [], "audience": [], "settings": {}, "sender": None}
    monkeypatch.setattr(notifications.requests, "post", lambda url, json, timeout: log["slack"].append(json["text"]) or type("R", (), {"raise_for_status": lambda self: None})())
    monkeypatch.setattr("src.tools.resend_client.send_email", lambda to, subject, html, sender=None: log["email"].append((to, subject, sender)))
    monkeypatch.setattr(notifications, "_campaign", lambda cid: {**CAMPAIGN, "id": cid})
    monkeypatch.setattr(notifications, "_settings", lambda org: log["settings"])
    monkeypatch.setattr(notifications, "_people", lambda org, audience: log["audience"].append(audience) or (MANAGERS if audience == "managers" else APPROVERS))
    monkeypatch.setattr(notifications, "_inbox", lambda org, users, kind, title, body, path, cid: log["inbox"].append((users, kind, title, path)))
    monkeypatch.setattr(notifications, "_sender", lambda org: log["sender"])
    return log


def test_a_waiting_gate_reaches_every_designated_approver_in_the_app(sent):
    notifications.notify_gate_opened("c1", 2, 1)
    assert sent["audience"] == ["approvers"]
    assert sent["inbox"] == [(["o", "a", "q"], "gate_opened", "Approval needed: Spice kits from home cooks", "/campaigns/c1")]


def test_slack_gets_one_message_with_a_link(sent):
    sent["settings"].update({"slack_webhook_url": "https://hooks.slack.com/x", "required_approvals": 2})
    notifications.notify_gate_opened("c1", 2, 1)
    assert "Gate 2 (round 1)" in sent["slack"][0] and "2 approvals needed" in sent["slack"][0]
    assert "/campaigns/c1|Open in CampaignIQ" in sent["slack"][0]


def test_email_goes_from_the_brands_own_account_one_per_person_skipping_those_who_turned_it_off(sent):
    sent["sender"] = {"api_key": "re_brand", "from": "Brewline <hello@brewline.coffee>", "reply_to": None}
    notifications.notify_gate_opened("c1", 1)
    assert [e[0] for e in sent["email"]] == [["owner@acme.io"], ["approver@acme.io"]]
    assert all(e[1] == "[CampaignIQ] Approval needed: Spice kits from home cooks" and e[2] == sent["sender"] for e in sent["email"])


def test_without_a_connected_account_email_needs_the_apps_own_switch(sent, monkeypatch):
    notifications.notify_gate_opened("c1", 1)
    assert sent["email"] == []  # the app's own account only reaches its owner until a domain is verified
    monkeypatch.setenv("NOTIFY_EMAIL", "true")
    notifications.notify_gate_opened("c1", 1)
    assert [e[0] for e in sent["email"]] == [["owner@acme.io"], ["approver@acme.io"]] and sent["email"][0][2] is None


def test_one_channel_failing_never_stops_the_others(sent, monkeypatch):
    monkeypatch.setattr(notifications, "_inbox", lambda *a: (_ for _ in ()).throw(ConnectionError("db down")))
    sent["settings"].update({"slack_webhook_url": "https://hooks.slack.com/x"})
    notifications.notify_gate_opened("c1", 1)
    assert len(sent["slack"]) == 1


def test_one_bad_address_doesnt_stop_the_other_emails(sent, monkeypatch):
    sent["sender"] = {"api_key": "re_brand", "from": "hello@brewline.coffee", "reply_to": None}

    def send(to, subject, html, sender=None):
        if to == ["owner@acme.io"]:
            raise ValueError("invalid address")
        sent["email"].append((to, subject, sender))

    monkeypatch.setattr("src.tools.resend_client.send_email", send)
    notifications.notify_gate_opened("c1", 1)
    assert [e[0] for e in sent["email"]] == [["approver@acme.io"]]


def test_slack_still_goes_when_the_recipient_lookup_fails(sent, monkeypatch):
    monkeypatch.setattr(notifications, "_people", lambda org, audience: (_ for _ in ()).throw(ConnectionError("rpc missing")))
    sent["settings"].update({"slack_webhook_url": "https://hooks.slack.com/x"})
    notifications.notify_gate_opened("c1", 1)
    assert len(sent["slack"]) == 1 and sent["inbox"] == []


def test_paused_email_notice_counts_as_sent_only_if_it_reached_someone(sent, monkeypatch):
    monkeypatch.setattr(notifications, "_inbox", lambda *a: (_ for _ in ()).throw(ConnectionError("db down")))
    assert notifications.notify_email_paused("org", "bounce rate 3.1%") is False  # nothing went out: tried again later


def test_a_paused_brand_account_is_not_used_to_send_notices(monkeypatch):
    config = {"mode": "live", "api_key": "re_x", "from": "a@b.co", "paused_reason": "complaints"}
    rpc = type("C", (), {"rpc": lambda self, name, args: type("Q", (), {"execute": lambda q: type("R", (), {"data": config})()})()})()
    monkeypatch.setattr(notifications, "_client", lambda: rpc)
    assert notifications._sender("org") is None
    config["paused_reason"] = None
    assert notifications._sender("org")["api_key"] == "re_x"


def test_notification_failures_never_raise(monkeypatch):
    monkeypatch.setattr(notifications, "_campaign", lambda cid: (_ for _ in ()).throw(ConnectionError("db down")))
    notifications.notify_gate_opened("c1", 1)  # no exception


def test_a_paused_campaign_and_paused_email_go_to_managers(sent):
    notifications.notify_hold("c1", "EXPIRED_OFFER", "The offer ended yesterday.", "critical")
    assert sent["audience"] == ["managers"] and sent["inbox"][0][1] == "campaign_hold"
    assert notifications.notify_email_paused("org", "complaint rate 0.07%") is True
    assert sent["audience"][-1] == "managers" and sent["inbox"][-1][3] == "/settings#email"


class FakeGates:
    def __init__(self, gates):
        self.gates, self.updates = gates, []

    def table(self, name):
        fake = self

        class Q:
            def select(self, *a): return self
            def is_(self, *a): return self
            def eq(self, col, val):
                self.id = val
                return self
            def update(self, row):
                fake.updates.append(row)
                return self
            def execute(self):
                return type("R", (), {"data": fake.gates})()

        return Q()


def test_escalates_only_past_the_deadline_and_to_managers(monkeypatch, sent):
    now = datetime.now(timezone.utc)
    gates = [
        {"id": "g-old", "campaign_id": "c1", "gate_number": 1, "round_number": 1, "created_at": (now - timedelta(hours=30)).isoformat()},
        {"id": "g-new", "campaign_id": "c2", "gate_number": 2, "round_number": 1, "created_at": (now - timedelta(hours=2)).isoformat()},
    ]
    fake = FakeGates(gates)
    monkeypatch.setattr(notifications, "_client", lambda: fake)
    sent["settings"].update({"approval_sla_hours": 24})
    assert notifications.escalate_overdue_gates() == 1
    assert sent["audience"] == ["managers"] and sent["inbox"][0][:3] == (["o"], "gate_overdue", "Approval overdue")
    assert len(fake.updates) == 1 and "escalated_at" in fake.updates[0]


def test_no_deadline_means_no_escalation(monkeypatch, sent):
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    monkeypatch.setattr(notifications, "_client", lambda: FakeGates([{"id": "g", "campaign_id": "c", "gate_number": 1, "round_number": 1, "created_at": old}]))
    assert notifications.escalate_overdue_gates() == 0
