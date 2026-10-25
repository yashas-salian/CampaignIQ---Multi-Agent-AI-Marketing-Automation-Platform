"""Crash tests in the database: members read the reports, only the worker
writes them, runs and applied revisions are audited, and approving an ad
whose current crash test is critical needs a reason at Gate 2."""
import json

import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def round_at_gate_2(db, new_user, act_as, as_admin):
    owner, approver, outsider = new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'approver')", (org, approver))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('Coffee', 'other', %s, %s) returning id", (owner, org)
    ).fetchone()[0]
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number, round_number) values (%s, %s, 2, 1) returning id", (cid, owner)
    ).fetchone()[0]
    return {"org": org, "owner": owner, "approver": approver, "outsider": outsider, "campaign": cid, "gate": gate}


def crash(db, c, risk="critical", revised_risk=None):
    return db.execute(
        "insert into crash_tests (campaign_id, org_id, user_id, round_number, scenario_set, rules_version, status, risk,"
        " revised_risk, report) values (%s, %s, %s, 1, 'marketing-risk-v1', 'rules-v1', 'COMPLETED', %s, %s, %s) returning id",
        (c["campaign"], c["org"], c["owner"], risk, revised_risk, json.dumps({"findings": []})),
    ).fetchone()[0]


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


def test_members_read_reports_outsiders_dont_nobody_writes(db, round_at_gate_2, act_as, as_admin):
    c = round_at_gate_2
    crash(db, c)
    count = "select count(*) from crash_tests where campaign_id = %s"
    act_as(c["approver"])
    assert db.execute(count, (c["campaign"],)).fetchone()[0] == 1
    act_as(c["outsider"])
    assert db.execute(count, (c["campaign"],)).fetchone()[0] == 0
    act_as(c["owner"])
    db.execute("savepoint w")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update crash_tests set risk = 'clear' where campaign_id = %s", (c["campaign"],))
    db.execute("rollback to savepoint w")
    as_admin()


def test_runs_and_applied_revisions_are_audited(db, round_at_gate_2):
    c = round_at_gate_2
    test_id = crash(db, c, "critical", "low")
    db.execute("update crash_tests set applied_at = now() where id = %s", (test_id,))
    actions = [r[0] for r in db.execute(
        "select action from audit_log where target_id = %s and action like 'campaign.crash_test%%' order by id", (str(c["campaign"]),))]
    assert actions == ["campaign.crash_test", "campaign.crash_test_applied"]


def test_a_critical_ad_needs_a_reason_to_approve(db, round_at_gate_2, act_as, as_admin):
    c = round_at_gate_2
    crash(db, c, "critical")
    assert "critical problem" in vote(db, act_as, as_admin, c["approver"], c["gate"])
    assert vote(db, act_as, as_admin, c["approver"], c["gate"], comment="The quote is a real customer, consent on file") == "ok"


def test_applying_a_clean_revision_lifts_the_rule(db, round_at_gate_2, act_as, as_admin):
    c = round_at_gate_2
    test_id = crash(db, c, "critical", "low")
    db.execute("update crash_tests set applied_at = now() where id = %s", (test_id,))
    assert db.execute("select public.crash_test_risk(%s, 1)", (c["campaign"],)).fetchone()[0] == "low"
    assert vote(db, act_as, as_admin, c["approver"], c["gate"]) == "ok"


def test_high_risk_and_rejections_need_no_reason(db, round_at_gate_2, act_as, as_admin):
    c = round_at_gate_2
    crash(db, c, "high")
    assert vote(db, act_as, as_admin, c["approver"], c["gate"], decision="reject") == "ok"
