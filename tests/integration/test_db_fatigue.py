"""Creative fatigue in the database: who can refresh or keep a creative, one
refresh waiting per campaign, dismissing cancels it, and members read but
never write alerts or outcomes."""
import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402


@pytest.fixture
def setup(db, new_user, act_as, as_admin):
    owner, marketer, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'marketer'), (%s, %s, 'viewer')",
               (org, marketer, org, viewer))
    cid = db.execute("insert into campaigns (idea, domain_category, user_id, org_id, status) values ('Coffee', 'food_beverage', %s, %s, "
                     "'awaiting_next_round') returning id", (owner, org)).fetchone()[0]
    alert = db.execute(
        "insert into creative_fatigue_alerts (campaign_id, org_id, channel, segment, status, recommendation, evidence) "
        "values (%s, %s, 'email', 'a', 'FATIGUE_CONFIRMED', 'TEST_REFRESH', %s) returning id",
        (cid, org, Jsonb({"refresh_constraints": {"avoid_hooks": ["Coffee ready on arrival."]}})),
    ).fetchone()[0]
    return {"org": org, "owner": owner, "marketer": marketer, "viewer": viewer, "outsider": outsider, "campaign": cid, "alert": alert}


def as_user(db, act_as, as_admin, user, sql, params):
    act_as(user)
    db.execute("savepoint s")
    try:
        row = db.execute(sql, params).fetchone()
        db.execute("release savepoint s")
        result = ("ok", row[0] if row else None)
    except psycopg.Error as exc:
        db.execute("rollback to savepoint s")
        result = (str(exc).split("\n")[0], None)
    as_admin()
    return result


REFRESH = "select request_creative_refresh(%s, %s)"


def test_marketers_refresh_viewers_cannot(db, setup, act_as, as_admin):
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, setup["viewer"], REFRESH, (setup["alert"], "NEW_HOOK"))[0]
    status, iid = as_user(db, act_as, as_admin, setup["marketer"], REFRESH, (setup["alert"], "NEW_HOOK"))
    assert status == "ok"
    row = db.execute("select strategy, constraints, domain_category, requested_by from creative_interventions where id = %s", (iid,)).fetchone()
    assert row[0] == "NEW_HOOK" and row[1] == {"avoid_hooks": ["Coffee ready on arrival."]} and row[2] == "food_beverage"
    assert str(row[3]) == setup["marketer"]
    assert db.execute("select state from creative_fatigue_alerts where id = %s", (setup["alert"],)).fetchone()[0] == "refreshing"
    assert "check constraint" in as_user(db, act_as, as_admin, setup["marketer"], REFRESH, (setup["alert"], "COPY_THEIRS"))[0]


def test_one_refresh_waits_per_campaign_and_a_new_pick_replaces_it(db, setup, act_as, as_admin):
    # The system proposed one; a person picks another before the next round.
    db.execute("insert into creative_interventions (alert_id, campaign_id, org_id, channel, strategy) values (%s, %s, %s, 'email', 'NEW_VISUAL')",
               (setup["alert"], setup["campaign"], setup["org"]))
    as_user(db, act_as, as_admin, setup["owner"], REFRESH, (setup["alert"], "NEW_ANGLE"))
    rows = db.execute("select strategy from creative_interventions where campaign_id = %s and outcome = 'pending'", (setup["campaign"],)).fetchall()
    assert rows == [("NEW_ANGLE",)]
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("insert into creative_interventions (campaign_id, org_id, channel, strategy) values (%s, %s, 'email', 'NEW_HOOK')",
                   (setup["campaign"], setup["org"]))
    db.execute("rollback to savepoint s")


def test_keeping_the_creative_cancels_the_waiting_refresh(db, setup, act_as, as_admin):
    as_user(db, act_as, as_admin, setup["marketer"], REFRESH, (setup["alert"], "NEW_HOOK"))
    assert as_user(db, act_as, as_admin, setup["owner"], "select dismiss_fatigue_alert(%s, %s)",
                   (setup["alert"], "Seasonal dip, it'll recover"))[0] == "ok"
    assert db.execute("select outcome from creative_interventions where alert_id = %s", (setup["alert"],)).fetchone()[0] == "CANCELLED"
    assert db.execute("select state, note from creative_fatigue_alerts where id = %s", (setup["alert"],)).fetchone() == \
        ("dismissed", "Seasonal dip, it'll recover")
    assert "this alert is closed" in as_user(db, act_as, as_admin, setup["owner"], REFRESH, (setup["alert"], "NEW_HOOK"))[0]
    assert db.execute("select count(*) from audit_log where action = 'creative.fatigue_dismissed' and target_id = %s",
                      (str(setup["campaign"]),)).fetchone()[0] == 1


def test_members_read_nobody_writes_directly(db, setup, act_as, as_admin):
    act_as(setup["viewer"])
    assert db.execute("select count(*) from creative_fatigue_alerts where campaign_id = %s", (setup["campaign"],)).fetchone()[0] == 1
    act_as(setup["outsider"])
    assert db.execute("select count(*) from creative_fatigue_alerts where campaign_id = %s", (setup["campaign"],)).fetchone()[0] == 0
    as_admin()
    assert "permission denied" in as_user(db, act_as, as_admin, setup["owner"],
                                          "update creative_fatigue_alerts set state = 'closed' where id = %s", (setup["alert"],))[0]
    assert "permission denied" in as_user(db, act_as, as_admin, setup["owner"],
                                          "update creative_interventions set outcome = 'IMPROVED' where campaign_id = %s", (setup["campaign"],))[0]
