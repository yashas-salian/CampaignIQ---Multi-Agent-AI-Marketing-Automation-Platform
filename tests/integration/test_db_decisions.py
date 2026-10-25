"""Decision intelligence in the database: the campaign_decisions table (read by
members, written only by the worker, audited), the Gate 1 override rule and
the 'blocked' status."""
import json

import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def campaign(db, new_user, act_as, as_admin):
    owner, approver, outsider = new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'approver')", (org, approver))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('Padel grips', 'other', %s, %s) returning id",
        (owner, org),
    ).fetchone()[0]
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number) values (%s, %s, 1) returning id", (cid, owner)
    ).fetchone()[0]
    return {"org": org, "owner": owner, "approver": approver, "outsider": outsider, "campaign": cid, "gate": gate}


def decide(db, c, decision="LAUNCH", hard_blocks=(), reasons=("STRONG_DEMAND",)):
    db.execute(
        "insert into campaign_decisions (campaign_id, org_id, user_id, decision, opportunity_score, uncertainty, reason_codes,"
        " hard_blocks, policy_version) values (%s, %s, %s, %s, 70, 0.15, %s, %s, 'decision-v1')",
        (c["campaign"], c["org"], c["owner"], decision, list(reasons), json.dumps(list(hard_blocks))),
    )


def vote(db, act_as, as_admin, user, gate, decision="approve", comment=None):
    act_as(user)
    db.execute("savepoint v")
    try:
        db.execute("insert into gate_approvals (gate_decision_id, decision, comment) values (%s, %s, %s)", (gate, decision, comment))
        db.execute("release savepoint v")
        result = "ok"
    except psycopg.Error as exc:
        db.execute("rollback to savepoint v")
        result = str(exc).split("\n")[0]
    as_admin()
    return result


def test_members_read_decisions_outsiders_dont_and_nobody_writes(db, campaign, act_as, as_admin):
    decide(db, campaign)
    count = "select count(*) from campaign_decisions where campaign_id = %s"
    act_as(campaign["approver"])
    assert db.execute(count, (campaign["campaign"],)).fetchone()[0] == 1
    act_as(campaign["outsider"])
    assert db.execute(count, (campaign["campaign"],)).fetchone()[0] == 0
    act_as(campaign["owner"])
    db.execute("savepoint w")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update campaign_decisions set decision = 'LAUNCH' where campaign_id = %s", (campaign["campaign"],))
    db.execute("rollback to savepoint w")
    as_admin()


def test_every_decision_is_audited(db, campaign):
    decide(db, campaign, "TEST_SMALL", reasons=("WEAK_PURCHASE_INTENT",))
    row = db.execute(
        "select details from audit_log where action = 'campaign.decision' and target_id = %s", (str(campaign["campaign"]),)
    ).fetchone()
    assert row and row[0]["decision"] == "TEST_SMALL" and row[0]["reasons"] == ["WEAK_PURCHASE_INTENT"]


def test_approving_against_a_kill_needs_a_reason(db, campaign, act_as, as_admin):
    decide(db, campaign, "KILL", reasons=("WEAK_DEMAND",))
    assert "needs a reason" in vote(db, act_as, as_admin, campaign["approver"], campaign["gate"])
    assert "needs a reason" in vote(db, act_as, as_admin, campaign["approver"], campaign["gate"], comment="ok")
    assert vote(db, act_as, as_admin, campaign["approver"], campaign["gate"],
                comment="Launching for a partner event we already committed to") == "ok"


def test_rejecting_never_needs_a_reason_and_launch_doesnt_either(db, campaign, act_as, as_admin):
    decide(db, campaign, "WAIT")
    assert vote(db, act_as, as_admin, campaign["approver"], campaign["gate"], decision="reject") == "ok"


def test_the_latest_decision_counts(db, campaign, act_as, as_admin):
    decide(db, campaign, "WAIT")
    # One test transaction shares a single now(); the real worker writes each decision separately.
    db.execute("update campaign_decisions set created_at = now() - interval '1 day' where campaign_id = %s", (campaign["campaign"],))
    decide(db, campaign, "LAUNCH")  # re-evaluated after interest rose
    assert vote(db, act_as, as_admin, campaign["approver"], campaign["gate"]) == "ok"


def test_a_hard_block_can_never_be_approved(db, campaign, act_as, as_admin):
    decide(db, campaign, "KILL", hard_blocks=[{"code": "PROHIBITED_PRODUCT", "detail": "weapons"}], reasons=("PROHIBITED_PRODUCT",))
    result = vote(db, act_as, as_admin, campaign["approver"], campaign["gate"], comment="I really want to run this one anyway")
    assert "is blocked" in result and "PROHIBITED_PRODUCT" in result


def test_blocked_is_a_valid_finished_status(db, campaign):
    db.execute("update campaigns set status = 'blocked' where id = %s", (campaign["campaign"],))
    usage = db.execute("select public.org_usage_unchecked(%s)", (campaign["org"],)).fetchone()[0]
    assert usage["used"]["active_campaigns"] == 0  # a blocked campaign doesn't use up the plan
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("update campaigns set status = 'paused' where id = %s", (campaign["campaign"],))
    db.execute("rollback to savepoint s")
