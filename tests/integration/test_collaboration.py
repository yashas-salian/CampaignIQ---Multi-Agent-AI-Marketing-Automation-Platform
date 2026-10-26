"""Comments and Gate-2 copy editing with version history."""
import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def setup(db, new_user, act_as, as_admin):
    owner, approver, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("update organizations set plan = 'pro' where id = %s", (org,))
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'approver'), (%s, %s, 'viewer')", (org, approver, org, viewer))
    cid = db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('i', 'other', %s, %s) returning id", (owner, org)
    ).fetchone()[0]
    db.execute("insert into iterations (campaign_id, user_id, round_number, copy_text, copy_text_b) values (%s, %s, 1, 'AI draft', 'AI draft B')", (cid, owner))
    db.execute("insert into gate_decisions (campaign_id, user_id, gate_number, round_number) values (%s, %s, 2, 1)", (cid, owner))
    return cid, {"owner": owner, "approver": approver, "viewer": viewer, "outsider": outsider}


def run(db, sql, params=()):
    db.execute("savepoint s")
    try:
        db.execute(sql, params)
        db.execute("release savepoint s")
        return "ok"
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        return str(exc).split("\n")[0]


def test_members_comment_outsiders_cannot(db, setup, act_as, as_admin):
    cid, u = setup
    act_as(u["viewer"])
    assert run(db, "insert into campaign_comments (campaign_id, body) values (%s, 'Love round 1')", (cid,)) == "ok"
    as_admin()
    act_as(u["outsider"])
    assert "row-level security" in run(db, "insert into campaign_comments (campaign_id, body) values (%s, 'hi')", (cid,))
    assert db.execute("select count(*) from campaign_comments").fetchone()[0] == 0


def test_edit_keeps_the_original_and_every_version(db, setup, act_as, as_admin):
    cid, u = setup
    act_as(u["approver"])
    # A substantial rewrite needs a reason (it's kept with the version, and proposed as a brand lesson).
    assert "say why" in run(db, "select edit_round_copy(%s, 1, 'a', 'Edited once')", (cid,))
    assert run(db, "select edit_round_copy(%s, 1, 'a', 'Edited once', 'The draft sounded too salesy')", (cid,)) == "ok"
    assert run(db, "select edit_round_copy(%s, 1, 'a', 'Edited twice', 'Tighter wording for the email')", (cid,)) == "ok"
    as_admin()
    assert db.execute("select reason, material from copy_revisions where campaign_id = %s and copy_text = 'Edited once'",
                      (cid,)).fetchone() == ("The draft sounded too salesy", True)
    versions = db.execute("select copy_text, edited_by is null from copy_revisions where campaign_id = %s and variant = 'a' order by id", (cid,)).fetchall()
    assert versions == [("AI draft", True), ("Edited once", False), ("Edited twice", False)]
    assert db.execute("select copy_text, copy_text_b from iterations where campaign_id = %s", (cid,)).fetchone() == ("Edited twice", "AI draft B")


def test_only_approvers_edit_and_only_while_gate_2_is_open(db, setup, act_as, as_admin):
    cid, u = setup
    act_as(u["viewer"])
    assert "only owners, admins and approvers" in run(db, "select edit_round_copy(%s, 1, 'a', 'x')", (cid,))
    as_admin()
    db.execute("update gate_decisions set decided_at = now(), decision = 'approve' where campaign_id = %s", (cid,))
    act_as(u["approver"])
    assert "while Gate 2 is open" in run(db, "select edit_round_copy(%s, 1, 'b', 'late edit')", (cid,))
