from datetime import datetime, timedelta, timezone

import pytest

from src import notifications

MEMBERS = [
    {"user_id": "o", "role": "owner", "email": "owner@acme.io"},
    {"user_id": "a", "role": "approver", "email": "approver@acme.io"},
    {"user_id": "m", "role": "marketer", "email": "marketer@acme.io"},
]


@pytest.fixture
def sent(monkeypatch):
    log = {"slack": [], "email": []}
    monkeypatch.setattr(notifications.requests, "post", lambda url, json, timeout: log["slack"].append(json["text"]) or type("R", (), {"raise_for_status": lambda self: None})())
    monkeypatch.setattr("src.tools.resend_client.send_email", lambda to, subject, html: log["email"].append((to, subject)))
    return log


def context(settings):
    return lambda cid: ({"id": cid, "idea": "Spice kits from home cooks", "org_id": "org", "user_id": "o"}, settings, MEMBERS)


def test_gate_opened_goes_to_slack_with_a_link(monkeypatch, sent):
    monkeypatch.setattr(notifications, "_org_context", context({"slack_webhook_url": "https://hooks.slack.com/x", "required_approvals": 2}))
    notifications.notify_gate_opened("c1", 2, 1)
    assert "Gate 2 (round 1)" in sent["slack"][0] and "2 approvals needed" in sent["slack"][0]
    assert "/campaigns/c1|Open in MarketingOS" in sent["slack"][0]
    assert sent["email"] == []  # email is opt-in


def test_email_goes_to_approvers_only_when_enabled(monkeypatch, sent):
    monkeypatch.setenv("NOTIFY_EMAIL", "true")
    monkeypatch.setattr(notifications, "_org_context", context({}))
    notifications.notify_gate_opened("c1", 1)
    assert sent["email"] == [(["owner@acme.io", "approver@acme.io"], "[MarketingOS] Approval needed: Spice kits from home cooks")]


def test_notification_failures_never_raise(monkeypatch):
    monkeypatch.setattr(notifications, "_org_context", lambda cid: (_ for _ in ()).throw(ConnectionError("db down")))
    notifications.notify_gate_opened("c1", 1)  # no exception


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
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: fake)
    monkeypatch.setenv("NOTIFY_EMAIL", "true")
    monkeypatch.setattr(notifications, "_org_context", context({"approval_sla_hours": 24}))
    assert notifications.escalate_overdue_gates() == 1
    assert sent["email"] == [(["owner@acme.io"], "[MarketingOS] Approval overdue")]
    assert len(fake.updates) == 1 and "escalated_at" in fake.updates[0]


def test_no_deadline_means_no_escalation(monkeypatch, sent):
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: FakeGates([{"id": "g", "campaign_id": "c", "gate_number": 1, "round_number": 1, "created_at": old}]))
    monkeypatch.setattr(notifications, "_org_context", context({}))
    assert notifications.escalate_overdue_gates() == 0
