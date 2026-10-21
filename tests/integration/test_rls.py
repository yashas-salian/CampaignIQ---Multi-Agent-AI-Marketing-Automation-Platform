"""Row-level security, checked against a real Postgres built from supabase/migrations."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


def campaign(db, user_id: str) -> str:
    return db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('idea', 'other', %s) returning id", (user_id,)
    ).fetchone()[0]


def test_users_only_see_their_own_campaigns(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    mine, theirs = campaign(db, alice), campaign(db, bob)
    act_as(alice)
    visible = {row[0] for row in db.execute("select id from campaigns")}
    assert mine in visible and theirs not in visible


def test_users_cannot_write_into_someone_elses_campaign(db, new_user, act_as):
    alice, bob = new_user(), new_user()
    theirs = campaign(db, bob)
    act_as(alice)
    assert db.execute("update campaigns set idea = 'hijacked' where id = %s", (theirs,)).rowcount == 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into campaigns (idea, domain_category, user_id) values ('x', 'other', %s)", (bob,))


def test_signup_creates_a_free_subscription(db, new_user):
    user_id = new_user()
    assert db.execute("select status from subscriptions where user_id = %s", (user_id,)).fetchone() == ("free",)


def test_users_cannot_upgrade_their_own_subscription(db, new_user, act_as):
    user_id = new_user()
    act_as(user_id)
    assert db.execute("update subscriptions set status = 'subscribed' where user_id = %s", (user_id,)).rowcount == 0


def test_masked_key_view_never_exposes_ciphertext(db):
    columns = {
        row[0]
        for row in db.execute("select column_name from information_schema.columns where table_name = 'provider_keys_masked'")
    }
    assert "encrypted_key" not in columns and "masked_key" in columns


def test_domain_correction_defaults_to_the_caller(db, new_user, act_as):
    alice = new_user()
    cid = campaign(db, alice)
    act_as(alice)
    db.execute(
        "insert into domain_corrections (campaign_id, idea, predicted_domain, corrected_domain) "
        "values (%s, 'i', 'other', 'education')",
        (cid,),
    )
    assert db.execute("select user_id from domain_corrections").fetchone()[0] == uuid.UUID(alice)


def test_realtime_publishes_the_tables_the_frontend_subscribes_to(db):
    tables = {row[0] for row in db.execute("select tablename from pg_publication_tables where pubname = 'supabase_realtime'")}
    assert {"campaigns", "iterations", "personas", "gate_decisions", "metrics"} <= tables
