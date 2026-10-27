"""Tamper-evident audit log: written by triggers, hash-chained, append-only."""
import pytest

psycopg = pytest.importorskip("psycopg")


def events(db, target_id=None, since=0):
    sql = "select action, actor_type, actor_id, details from audit_log where id > %s"
    params = [since]
    if target_id:
        sql += " and target_id = %s"
        params.append(str(target_id))
    return db.execute(sql + " order by id", params).fetchall()


def last_id(db):
    return db.execute("select coalesce(max(id), 0) from audit_log").fetchone()[0]


def test_campaign_lifecycle_is_recorded_with_the_actor(db, new_user, act_as, as_admin):
    user = new_user()
    act_as(user)
    # Already scored, as at Gate 1, where people correct the category.
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, feasibility_score) values ('Spice kits', 'other', %s, 60) returning id",
        (user,),
    ).fetchone()[0]
    db.execute("update campaigns set domain_category = 'food_beverage', stop_requested = true where id = %s", (cid,))
    as_admin()
    db.execute("update campaigns set status = 'awaiting_gate_1' where id = %s", (cid,))
    rows = events(db, cid)
    assert [r[0] for r in rows] == [
        "campaign.created", "campaign.stop_requested", "campaign.category_corrected", "campaign.status_changed",
    ]
    assert rows[0][1:3] == ("user", __import__("uuid").UUID(user))
    assert rows[2][3] == ["other", "food_beverage"]
    assert rows[3][1] == "system"  # the worker, not a person


def test_gate_decisions_and_membership_changes(db, new_user, act_as, as_admin):
    owner, member = new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    start = last_id(db)
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, member))
    act_as(owner)
    db.execute("select set_member_role(%s, %s, 'approver')", (org, member))
    as_admin()
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('i', 'other', %s, %s) returning id", (owner, org)
    ).fetchone()[0]
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number) values (%s, %s, 1) returning id", (cid, owner)
    ).fetchone()[0]
    act_as(member)
    db.execute("insert into gate_approvals (gate_decision_id, decision, comment) values (%s, 'approve', 'ship it')", (gate,))
    as_admin()
    actions = [r[0] for r in events(db, since=start)]
    assert actions == ["membership.added", "membership.role_changed", "campaign.created", "gate.vote", "gate.decided"]


def test_secrets_never_reach_the_log(db, new_user):
    user = new_user()
    start = last_id(db)
    db.execute("select store_provider_key(%s, 'llm', 'sk-super-secret-9999')", (user,))
    details = str(events(db, since=start))
    assert "sk-super-secret" not in details and "****9999" in details


def test_chain_verifies_and_detects_tampering(db, new_user):
    new_user()
    db.execute("insert into campaigns (idea, domain_category, user_id) select 'x', 'other', id from auth.users limit 1")
    assert db.execute("select verify_audit_chain()").fetchone()[0] is None
    # Even a superuser has to switch the guard trigger off to rewrite history...
    db.execute("alter table audit_log disable trigger audit_log_no_update")
    victim = db.execute("select max(id) from audit_log").fetchone()[0]
    db.execute("update audit_log set details = '{\"forged\": true}' where id = %s", (victim,))
    db.execute("alter table audit_log enable trigger audit_log_no_update")
    # ...and the chain still gives it away.
    assert db.execute("select verify_audit_chain()").fetchone()[0] == victim


def test_verification_does_not_depend_on_the_session_time_zone(db, new_user):
    new_user()
    db.execute("insert into campaigns (idea, domain_category, user_id) select 'x', 'other', id from auth.users limit 1")
    db.execute("set local time zone 'Asia/Kolkata'")
    assert db.execute("select verify_audit_chain()").fetchone()[0] is None


@pytest.mark.parametrize("role", ["service_role", "authenticated"])
def test_append_only_for_every_role(db, new_user, role):
    new_user()
    db.execute(f"set local role {role}")
    for sql in ("delete from audit_log", "update audit_log set action = 'x'", "insert into audit_log (actor_type, action, target_type, hash) values ('user', 'x', 'x', 'x')"):
        db.execute("savepoint s")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute(sql)
        db.execute("rollback to savepoint s")


def test_only_org_managers_read_the_org_trail(db, new_user, act_as, as_admin):
    owner, viewer = new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, viewer))
    act_as(owner)
    assert db.execute("select count(*) from audit_log where org_id = %s", (org,)).fetchone()[0] >= 2
    as_admin()
    act_as(viewer)
    assert db.execute("select count(*) from audit_log where org_id = %s", (org,)).fetchone()[0] == 0
