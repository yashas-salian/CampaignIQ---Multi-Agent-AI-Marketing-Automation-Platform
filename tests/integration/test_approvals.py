"""Multi-approver gates: votes, quorum, self-approval policy."""
import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def setup(db, new_user, act_as, as_admin):
    """Org with an owner (campaign creator) and three approvers; one open gate."""
    owner = new_user()
    approvers = [new_user() for _ in range(3)]
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    for a in approvers:
        db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'approver')", (org, a))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('i', 'other', %s, %s) returning id", (owner, org)
    ).fetchone()[0]
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number) values (%s, %s, 1) returning id", (cid, owner)
    ).fetchone()[0]
    return org, owner, approvers, gate


def policy(db, org, **values):
    cols = ", ".join(values)
    db.execute(
        f"insert into org_settings (org_id, {cols}) values (%s, {', '.join(['%s'] * len(values))})",
        (org, *values.values()),
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


def state(db, gate):
    return db.execute("select decision, decided_at is not null from gate_decisions where id = %s", (gate,)).fetchone()


def test_single_approval_decides_by_default(db, setup, act_as, as_admin):
    _, _, approvers, gate = setup
    assert vote(db, act_as, as_admin, approvers[0], gate) == "ok"
    assert state(db, gate) == ("approve", True)


def test_quorum_waits_for_enough_approvals(db, setup, act_as, as_admin):
    org, _, approvers, gate = setup
    policy(db, org, required_approvals=2)
    vote(db, act_as, as_admin, approvers[0], gate, comment="looks good")
    assert state(db, gate) == (None, False)
    vote(db, act_as, as_admin, approvers[1], gate, "edit", comment="picked another persona")
    assert state(db, gate) == ("edit", True)
    comment = db.execute("select comment from gate_decisions where id = %s", (gate,)).fetchone()[0]
    assert comment == "looks good\npicked another persona"


def test_any_reject_rejects(db, setup, act_as, as_admin):
    org, _, approvers, gate = setup
    policy(db, org, required_approvals=3)
    vote(db, act_as, as_admin, approvers[0], gate)
    vote(db, act_as, as_admin, approvers[1], gate, "reject")
    assert state(db, gate) == ("reject", True)


def test_decided_gates_take_no_more_votes_and_votes_are_one_per_person(db, setup, act_as, as_admin):
    org, _, approvers, gate = setup
    policy(db, org, required_approvals=2)
    vote(db, act_as, as_admin, approvers[0], gate)
    assert "duplicate key" in vote(db, act_as, as_admin, approvers[0], gate)
    vote(db, act_as, as_admin, approvers[1], gate)
    assert "already been decided" in vote(db, act_as, as_admin, approvers[2], gate)


def test_self_approval_can_be_forbidden(db, setup, act_as, as_admin):
    org, owner, approvers, gate = setup
    assert vote(db, act_as, as_admin, owner, gate) == "ok"  # allowed by default (solo use)
    db.execute("delete from gate_approvals")
    db.execute("update gate_decisions set decision = null, decided_at = null where id = %s", (gate,))
    policy(db, org, forbid_self_approval=True)
    assert "other than the campaign's creator" in vote(db, act_as, as_admin, owner, gate)
    assert vote(db, act_as, as_admin, approvers[0], gate) == "ok"


def test_votes_cannot_be_cast_for_someone_else(db, setup, act_as, as_admin):
    _, _, approvers, gate = setup
    act_as(approvers[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute(
            "insert into gate_approvals (gate_decision_id, user_id, decision) values (%s, %s, 'approve')", (gate, approvers[1])
        )


def test_policy_is_visible_to_members_but_the_webhook_only_to_managers(db, setup, act_as, as_admin):
    org, _, approvers, _ = setup
    policy(db, org, required_approvals=2, slack_webhook_url="https://hooks.slack.com/services/T/B/x")
    act_as(approvers[0])
    assert db.execute("select org_approval_policy(%s)->>'required_approvals'", (org,)).fetchone()[0] == "2"
    assert db.execute("select count(*) from org_settings").fetchone()[0] == 0


def test_only_managers_change_the_policy(db, setup, act_as):
    org, _, approvers, _ = setup
    act_as(approvers[0])
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into org_settings (org_id, required_approvals) values (%s, 1)", (org,))
