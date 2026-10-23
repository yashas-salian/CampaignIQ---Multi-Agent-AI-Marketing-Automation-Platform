"""Market alerts, playbooks and the A/B decision column, against a real Postgres."""
import json

import pytest

psycopg = pytest.importorskip("psycopg")


def campaign(db, user_id: str) -> tuple[str, str]:
    row = db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('idea', 'education', %s) returning id, org_id", (user_id,)
    ).fetchone()
    return row[0], row[1]


def alert(db, campaign_id, org_id) -> int:
    return db.execute(
        "insert into market_alerts (campaign_id, org_id, kind, detail) values (%s, %s, 'trend', %s) returning id",
        (campaign_id, org_id, json.dumps({"keyword": "budget app", "value": 72, "baseline": 30, "ratio": 2.4})),
    ).fetchone()[0]


def test_market_alerts_follow_the_campaign_and_can_only_be_dismissed(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    cid, org = campaign(db, alice)
    aid = alert(db, cid, org)

    act_as(bob)
    assert db.execute("select count(*) from market_alerts").fetchone()[0] == 0

    act_as(alice)
    assert db.execute("select kind from market_alerts where id = %s", (aid,)).fetchone()[0] == "trend"
    assert db.execute("update market_alerts set dismissed_at = now() where id = %s", (aid,)).rowcount == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update market_alerts set kind = 'news' where id = %s", (aid,))


def test_members_cannot_forge_market_alerts(db, new_user, act_as):
    alice = new_user()
    cid, org = campaign(db, alice)
    act_as(alice)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        alert(db, cid, org)


def test_playbooks_are_readable_by_the_org_only_and_written_by_the_service(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    _, org = campaign(db, alice)
    db.execute(
        "insert into playbooks (org_id, domain_category, content, stats) values (%s, 'education', %s, %s)",
        (org, json.dumps({"headline": "Humour wins", "do": [], "avoid": [], "audience": [], "next_test": ""}), json.dumps({"rounds": 3})),
    )
    act_as(bob)
    assert db.execute("select count(*) from playbooks").fetchone()[0] == 0
    act_as(alice)
    assert db.execute("select content->>'headline' from playbooks").fetchone()[0] == "Humour wins"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update playbooks set content = '{}' where org_id = %s", (org,))


def test_anon_sees_no_alerts_or_playbooks(db, act_as):
    act_as(None)
    for table in ("market_alerts", "playbooks"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(f"select * from {table}")
        db.execute("rollback")
        act_as(None)


def test_campaigns_carry_ab_decision_and_market_watch(db):
    cols = {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'campaigns'")}
    assert {"ab_decision", "market_watch"} <= cols
