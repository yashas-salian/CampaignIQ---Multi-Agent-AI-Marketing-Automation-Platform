"""Notifications in the database: who is designated to hear about approvals,
each person's in-app inbox and email preference, and isolation."""
import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def team(db, new_user, act_as, as_admin):
    owner, admin, approver, marketer, viewer, outsider = (new_user() for _ in range(6))
    act_as(owner)
    org = db.execute("select create_organization('Brewline')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s,%s,'admin'),(%s,%s,'approver'),(%s,%s,'marketer'),(%s,%s,'viewer')",
               (org, admin, org, approver, org, marketer, org, viewer))
    return {"org": org, "owner": owner, "admin": admin, "approver": approver, "marketer": marketer, "viewer": viewer, "outsider": outsider}


def run(db, act_as, as_admin, user, sql, params=()):
    act_as(user)
    db.execute("savepoint s")
    try:
        rows = db.execute(sql, params).fetchall()
        db.execute("release savepoint s")
        out = ("ok", rows)
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        out = (str(exc).split("\n")[0], None)
    as_admin()
    return out


def recipients(db, team, audience="approvers"):
    rows = db.execute("select user_id, email_on from notification_recipients(%s, %s)", (team["org"], audience)).fetchall()
    return {str(u): on for u, on in rows}


def test_by_default_everyone_who_can_approve_hears_about_approvals(db, team):
    assert set(recipients(db, team)) == {str(team["owner"]), str(team["admin"]), str(team["approver"])}
    assert set(recipients(db, team, "managers")) == {str(team["owner"]), str(team["admin"])}


def test_managers_designate_who_hears_about_approvals(db, team, act_as, as_admin):
    sql = "select set_notification_people(%s, %s)"
    assert run(db, act_as, as_admin, team["marketer"], sql, (team["org"], [team["approver"]]))[0].startswith("only owners and admins")
    assert run(db, act_as, as_admin, team["owner"], sql, (team["org"], [team["approver"], team["marketer"]]))[0] == "ok"
    assert set(recipients(db, team)) == {str(team["approver"])}  # a marketer can't approve: never designated
    stored = lambda: [str(u) for u in db.execute("select notify_user_ids from org_settings where org_id = %s", (team["org"],)).fetchone()[0]]  # noqa: E731
    assert stored() == [str(team["approver"])]
    # Someone who left is dropped rather than blocking the save.
    assert run(db, act_as, as_admin, team["owner"], sql, (team["org"], [team["outsider"], team["admin"]]))[0] == "ok"
    assert stored() == [str(team["admin"])]


def test_if_nobody_designated_can_still_approve_everyone_who_can_hears(db, team, act_as, as_admin):
    assert run(db, act_as, as_admin, team["owner"], "select set_notification_people(%s, %s)", (team["org"], [team["approver"]]))[0] == "ok"
    db.execute("update memberships set role = 'viewer' where org_id = %s and user_id = %s", (team["org"], team["approver"]))
    assert set(recipients(db, team)) == {str(team["owner"]), str(team["admin"])}


def test_each_person_can_turn_off_notification_emails(db, team, act_as, as_admin):
    assert run(db, act_as, as_admin, team["approver"], "select set_notification_email(false)")[0] == "ok"
    assert recipients(db, team)[str(team["approver"])] is False
    assert recipients(db, team)[str(team["owner"])] is True


def test_the_inbox_is_each_persons_own(db, team, act_as, as_admin):
    db.execute("select notify_users(%s, %s, 'gate_opened', 'Gate 1 is waiting', 'Coffee to go', '/campaigns/x', null)",
               (team["org"], [team["owner"], team["approver"]]))
    mine = run(db, act_as, as_admin, team["approver"], "select id, title, read_at from notifications")[1]
    assert len(mine) == 1 and mine[0][1] == "Gate 1 is waiting" and mine[0][2] is None
    assert run(db, act_as, as_admin, team["marketer"], "select count(*) from notifications")[1] == [(0,)]
    assert run(db, act_as, as_admin, team["approver"], "select mark_notifications_read(null)")[0] == "ok"
    assert db.execute("select read_at is not null from notifications where user_id = %s", (team["approver"],)).fetchone()[0]
    assert db.execute("select read_at from notifications where user_id = %s", (team["owner"],)).fetchone()[0] is None
    assert "row-level security" in run(db, act_as, as_admin, team["approver"],
                                       "insert into notifications (user_id, org_id, kind, title) values (%s, %s, 'x', 'x') returning id",
                                       (team["approver"], team["org"]))[0]


def test_only_the_worker_sends_notifications(db, team, act_as, as_admin):
    assert "permission denied" in run(db, act_as, as_admin, team["owner"],
                                      "select notify_users(%s, %s, 'x', 'x', null, null, null)", (team["org"], [team["owner"]]))[0]
    assert "permission denied" in run(db, act_as, as_admin, team["owner"], "select * from notification_recipients(%s, 'approvers')", (team["org"],))[0]
