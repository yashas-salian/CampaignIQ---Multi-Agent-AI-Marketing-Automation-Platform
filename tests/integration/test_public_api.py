"""API keys and outbound webhooks."""
import hashlib
import hmac

import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def org(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    org_id = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    return org_id, owner


def test_keys_are_shown_once_and_stored_hashed(db, org, act_as, as_admin):
    org_id, owner = org
    act_as(owner)
    raw = db.execute("select create_api_key(%s, 'CI', array['read','write'])", (org_id,)).fetchone()[0]
    assert raw.startswith("ciq_") and len(raw) == 52
    row = db.execute("select prefix, key_hash, scopes from api_keys where org_id = %s", (org_id,)).fetchone()
    as_admin()
    assert row[0] == raw[:12] and row[1] == hashlib.sha256(raw.encode()).hexdigest() and raw not in str(row)
    looked_up = db.execute("select org_id, scopes, rate_limited from api_key_lookup(%s)", (raw,)).fetchone()
    assert looked_up == (__import__("uuid").UUID(org_id) if isinstance(org_id, str) else org_id, ["read", "write"], False)


def test_revoked_and_unknown_keys_resolve_to_nothing(db, org, act_as, as_admin):
    org_id, owner = org
    act_as(owner)
    raw = db.execute("select create_api_key(%s, 'temp')", (org_id,)).fetchone()[0]
    key_id = db.execute("select id from api_keys where prefix = %s", (raw[:12],)).fetchone()[0]
    db.execute("select revoke_api_key(%s)", (key_id,))
    as_admin()
    assert db.execute("select count(*) from api_key_lookup(%s)", (raw,)).fetchone()[0] == 0
    assert db.execute("select count(*) from api_key_lookup('ciq_nope')").fetchone()[0] == 0


def test_rate_limit_per_minute(db, org, act_as, as_admin):
    org_id, owner = org
    act_as(owner)
    raw = db.execute("select create_api_key(%s, 'busy')", (org_id,)).fetchone()[0]
    as_admin()
    flags = [db.execute("select rate_limited from api_key_lookup(%s, 3)", (raw,)).fetchone()[0] for _ in range(5)]
    assert flags == [False, False, False, True, True]


def test_only_managers_create_keys_and_users_cannot_resolve_them(db, org, new_user, act_as, as_admin):
    org_id, _ = org
    viewer = new_user()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org_id, viewer))
    act_as(viewer)
    db.execute("savepoint s")
    with pytest.raises(psycopg.Error, match="only owners and admins"):
        db.execute("select create_api_key(%s, 'x')", (org_id,))
    db.execute("rollback to savepoint s")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from api_key_lookup('ciq_x')")


def test_events_fan_out_to_matching_webhooks_signed(db, org, act_as, as_admin):
    org_id, owner = org
    act_as(owner)
    db.execute("insert into webhooks (org_id, url, events) values (%s, 'https://hooks.example.com/a', array['campaign.*'])", (org_id,))
    db.execute("insert into webhooks (org_id, url, events) values (%s, 'https://hooks.example.com/b', array['gate.decided'])", (org_id,))
    as_admin()
    db.execute("update organizations set plan = 'pro' where id = %s", (org_id,))
    db.execute("insert into campaigns (idea, domain_category, user_id, org_id) values ('Spice kits', 'other', %s, %s)", (owner, org_id))
    rows = db.execute(
        "select w.url, d.event, d.payload, d.net_request_id, w.secret from webhook_deliveries d join webhooks w on w.id = d.webhook_id"
    ).fetchall()
    assert [(r[0], r[1]) for r in rows] == [("https://hooks.example.com/a", "campaign.created")]
    url, event, payload, request_id, secret = rows[0]
    assert payload["data"]["idea"] == "Spice kits" and payload["organization_id"] == str(org_id)
    queued = db.execute("select url, headers, body from net.http_request_queue where id = %s", (request_id,)).fetchone()
    assert queued[0] == url
    body = bytes(queued[2]).decode() if queued[2] is not None else ""
    expected = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    assert queued[1]["X-CampaignIQ-Signature"] == expected and queued[1]["X-CampaignIQ-Event"] == event
    assert queued[1]["X-MarketingOS-Signature"] == expected and queued[1]["X-MarketingOS-Event"] == event  # old names, for now


def test_webhook_urls_must_be_https(db, org, act_as):
    org_id, owner = org
    act_as(owner)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into webhooks (org_id, url) values (%s, 'http://insecure.example.com')", (org_id,))


def test_event_matching():
    import psycopg as pg

    with pg.connect("postgresql://postgres:postgres@127.0.0.1:54322/postgres") as conn:
        check = lambda events, action: conn.execute("select webhook_matches(%s, %s)", (events, action)).fetchone()[0]  # noqa: E731
        assert check(["*"], "anything") and check(["gate.*"], "gate.vote") and check(["gate.decided"], "gate.decided")
        assert not check(["gate.*"], "campaign.created") and not check(["gate.decided"], "gate.vote")
