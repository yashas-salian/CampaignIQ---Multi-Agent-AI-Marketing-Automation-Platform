"""Plans and usage limits, enforced in the database."""
import pytest

psycopg = pytest.importorskip("psycopg")


def personal(db, user):
    return db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]


def add_campaign(db, user, org=None):
    db.execute("savepoint c")
    try:
        db.execute(
            "insert into campaigns (idea, domain_category, user_id, org_id) values ('i', 'other', %s, %s)", (user, org)
        )
        db.execute("release savepoint c")
        return "ok"
    except psycopg.Error as exc:
        db.execute("rollback to savepoint c")
        return str(exc).split("\n")[0]


def test_free_plan_caps_campaigns_per_day(db, new_user):
    user = new_user()
    assert [add_campaign(db, user) for _ in range(3)] == ["ok"] * 3
    assert add_campaign(db, user).startswith("usage limit: daily campaign limit reached (3 per day on the free plan)")


def test_active_campaign_cap(db, new_user):
    db.execute("update plan_limits set active_campaigns = 2 where plan = 'free'")  # rolled back after the test
    user = new_user()
    assert [add_campaign(db, user) for _ in range(2)] == ["ok"] * 2
    assert add_campaign(db, user).startswith("usage limit: active campaign limit reached (2 at a time on the free plan)")


def test_finished_campaigns_free_a_slot_but_the_daily_cap_still_applies(db, new_user):
    user = new_user()
    for _ in range(3):
        add_campaign(db, user)
    db.execute("update campaigns set status = 'completed' where user_id = %s", (user,))
    assert add_campaign(db, user).startswith("usage limit: daily campaign limit reached (3 per day")


def test_pro_and_enterprise_raise_the_limits(db, new_user):
    user = new_user()
    db.execute("update organizations set plan = 'enterprise' where id = %s", (personal(db, user),))
    assert all(add_campaign(db, user) == "ok" for _ in range(10))


def test_quota_error_is_readable_before_dispatch(db, new_user, act_as):
    user = new_user()
    org = personal(db, user)
    for _ in range(3):
        add_campaign(db, user)
    act_as(user)
    assert db.execute("select campaign_quota_error(%s)", (org,)).fetchone()[0].startswith("daily campaign limit")
    assert db.execute("select my_personal_org()").fetchone()[0] == org


def test_outsiders_learn_nothing_about_another_orgs_usage(db, new_user, act_as):
    owner, outsider = new_user(), new_user()
    org = personal(db, owner)
    act_as(outsider)
    assert db.execute("select org_usage(%s)", (org,)).fetchone()[0] is None
    assert db.execute("select campaign_quota_error(%s)", (org,)).fetchone()[0] == "organisation not found"


def test_member_limit(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    org = db.execute("select create_organization('Small team')").fetchone()[0]
    as_admin()
    for _ in range(4):  # owner + 4 = the free plan's 5
        db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, new_user()))
    with pytest.raises(psycopg.Error, match="already has 5 members"):
        db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, new_user()))


def test_tools_runs_per_day(db, new_user):
    user = new_user()
    for _ in range(20):
        db.execute("insert into capability_runs (user_id, capability) values (%s, 'image')", (user,))
    with pytest.raises(psycopg.Error, match="20 Tools runs per day"):
        db.execute("insert into capability_runs (user_id, capability) values (%s, 'image')", (user,))


def test_token_budget(db, new_user):
    user = new_user()
    org = personal(db, user)
    assert db.execute("select token_budget_error(%s)", (org,)).fetchone()[0] is None
    db.execute(
        "insert into llm_usage (user_id, org_id, provider, prompt_tokens, completion_tokens, latency_ms, ok) "
        "values (%s, %s, 'groq', 100000, 60000, 900, true)",
        (user, org),
    )
    assert "daily AI budget used (150000 tokens on the free plan)" in db.execute("select token_budget_error(%s)", (org,)).fetchone()[0]


def test_subscribing_upgrades_the_personal_org(db, new_user):
    user = new_user()
    db.execute("update subscriptions set status = 'subscribed' where user_id = %s", (user,))
    assert db.execute("select plan from organizations where id = %s", (personal(db, user),)).fetchone()[0] == "pro"


def test_members_cannot_change_the_plan(db, new_user, act_as):
    user = new_user()
    org = personal(db, user)
    act_as(user)
    with pytest.raises(psycopg.Error, match="changed through billing"):
        db.execute("update organizations set plan = 'enterprise' where id = %s", (org,))
