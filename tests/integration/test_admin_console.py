"""Internal admin console: operators only, everything audited."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def admin(db, new_user):
    user = new_user()
    db.execute("insert into platform_admins (user_id) values (%s)", (user,))
    return user


def test_non_admins_are_refused(db, new_user, act_as):
    act_as(new_user())
    assert db.execute("select is_platform_admin()").fetchone()[0] is False
    with pytest.raises(psycopg.Error, match="platform admins only"):
        db.execute("select admin_overview()")


def test_overview_and_org_search(db, admin, new_user, act_as):
    owner = new_user()
    act_as(owner)
    db.execute("select create_organization('Searchable Co')")
    act_as(admin)
    overview = db.execute("select admin_overview()").fetchone()[0]
    assert overview["users"] >= 2 and overview["organizations"] >= 1
    rows = db.execute("select name, members from admin_orgs('Searchable')").fetchall()
    assert ("Searchable Co", 1) in rows


def test_plan_override_is_audited_with_the_operator(db, admin, new_user, act_as, as_admin):
    user = new_user()
    org = db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]
    act_as(admin)
    db.execute("select admin_set_plan(%s, 'enterprise')", (org,))
    as_admin()
    assert db.execute("select plan from organizations where id = %s", (org,)).fetchone()[0] == "enterprise"
    actor = db.execute("select actor_id from audit_log where action = 'admin.plan_changed' order by id desc limit 1").fetchone()[0]
    assert actor == uuid.UUID(admin)


def test_members_still_cannot_change_plans(db, new_user, act_as):
    user = new_user()
    org = db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]
    act_as(user)
    with pytest.raises(psycopg.Error, match="changed through billing"):
        db.execute("update organizations set plan = 'pro' where id = %s", (org,))


def test_dead_letter_retry(db, admin, act_as, as_admin):
    delivery = db.execute(
        "insert into deliveries (campaign_id, round_number, channel, status, attempts) values ('c-dead', 1, 'email', 'dead', 5) returning id"
    ).fetchone()[0]
    act_as(admin)
    assert [r[0] for r in db.execute("select id from admin_dead_deliveries()").fetchall()] == [delivery]
    db.execute("select admin_retry_delivery(%s)", (delivery,))
    as_admin()
    assert db.execute("select status, attempts from deliveries where id = %s", (delivery,)).fetchone() == ("failed", 4)


def test_flags_and_audit_verification(db, admin, act_as):
    act_as(admin)
    db.execute("select admin_set_flag('new_editor', true, 25, 'Rich text editor')")
    assert [(f[0], f[2], f[3]) for f in db.execute("select key, description, enabled, rollout_percent from admin_flags()").fetchall()] == [("new_editor", True, 25)]
    assert db.execute("select admin_verify_audit()->>'intact'").fetchone()[0] == "true"
