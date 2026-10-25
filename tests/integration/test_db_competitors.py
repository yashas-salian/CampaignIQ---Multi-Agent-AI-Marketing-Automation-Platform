"""Competitor intelligence in the database: who manages the watch list, sources
stay unfetched until approved, a repeated story only adds its outlet, and
members read but never write what was observed."""
import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402


@pytest.fixture
def org(db, new_user, act_as, as_admin):
    owner, marketer, viewer, outsider = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org_id = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'marketer'), (%s, %s, 'viewer')",
               (org_id, marketer, org_id, viewer))
    return {"org": org_id, "owner": owner, "marketer": marketer, "viewer": viewer, "outsider": outsider}


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


UPSERT = "select upsert_competitor(%s, %s, %s)"


def competitor(db, act_as, as_admin, o):
    status, cid = as_user(db, act_as, as_admin, o["marketer"], UPSERT, (o["org"], "BrewCo", "https://brewco.example"))
    assert status == "ok", status
    return cid


def test_owners_admins_and_marketers_manage_the_watch_list(db, org, act_as, as_admin):
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, org["viewer"], UPSERT, (org["org"], "BrewCo", None))[0]
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, org["outsider"], UPSERT, (org["org"], "BrewCo", None))[0]
    cid = competitor(db, act_as, as_admin, org)
    assert competitor(db, act_as, as_admin, org) == cid  # saving again updates, it doesn't duplicate
    assert db.execute("select keywords from competitors where id = %s", (cid,)).fetchone()[0] == ["BrewCo"]
    assert db.execute("select count(*) from audit_log where action = 'competitor.saved' and target_id = %s", (str(cid),)).fetchone()[0] == 2


def test_sources_wait_for_approval(db, org, act_as, as_admin):
    cid = competitor(db, act_as, as_admin, org)
    add = "select add_competitor_source(%s, %s, %s)"
    assert "needs a web address" in as_user(db, act_as, as_admin, org["marketer"], add, (cid, "webpage", "brewco.example"))[0]
    _, sid = as_user(db, act_as, as_admin, org["marketer"], add, (cid, "webpage", "https://brewco.example/pricing"))
    _, bsky = as_user(db, act_as, as_admin, org["marketer"], add, (cid, "bluesky", "@BrewCo.bsky.social"))
    assert db.execute("select approved, status from competitor_sources where id = %s", (sid,)).fetchone() == (False, "never")
    assert db.execute("select locator from competitor_sources where id = %s", (bsky,)).fetchone()[0] == "brewco.bsky.social"
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, org["viewer"],
                                                          "select approve_competitor_source(%s, true)", (sid,))[0]
    assert as_user(db, act_as, as_admin, org["owner"], "select approve_competitor_source(%s, true)", (sid,))[0] == "ok"
    approved, by = db.execute("select approved, approved_by from competitor_sources where id = %s", (sid,)).fetchone()
    assert approved and str(by) == org["owner"]
    as_user(db, act_as, as_admin, org["owner"], "select archive_competitor(%s)", (cid,))
    assert db.execute("select count(*) from competitor_sources where competitor_id = %s and approved", (cid,)).fetchone()[0] == 0


def test_a_repeated_story_adds_its_outlet_not_a_new_signal(db, org, act_as, as_admin):
    cid = competitor(db, act_as, as_admin, org)
    record = ("select event_id, is_new from record_competitor_event(%s, null, 'PRODUCT_LAUNCH', 'BrewCo launches X', %s, %s, %s, %s, "
              "'story-1', 0.6)")
    first = db.execute(record, (cid, Jsonb({"headline": "BrewCo launches X"}), "https://a.example", "Reuters", "2026-10-20T10:00:00Z")).fetchone()
    again = db.execute(record, (cid, Jsonb({}), "https://b.example", "Yahoo", "2026-10-20T12:00:00Z")).fetchone()
    earlier = db.execute(record, (cid, Jsonb({}), "https://c.example", "AP", "2026-10-20T08:00:00Z")).fetchone()
    assert first[1] is True and again == (first[0], False) and earlier == (first[0], False)
    reports, outlets, original = db.execute("select reports, outlets, original_outlet from competitor_events where id = %s",
                                            (first[0],)).fetchone()
    assert reports == 3 and outlets == ["Reuters", "Yahoo", "AP"] and original == "AP"  # the earliest report is the original
    assert db.execute("select count(*) from competitor_events where competitor_id = %s", (cid,)).fetchone()[0] == 1


def test_members_read_people_decide_only_the_worker_records(db, org, act_as, as_admin):
    cid = competitor(db, act_as, as_admin, org)
    eid = db.execute("select event_id from record_competitor_event(%s, null, 'OFFER_CHANGE', 'x', '{}', null, null, null, 'k', 0.9)",
                     (cid,)).fetchone()[0]
    iid = db.execute("insert into competitor_insights (competitor_id, org_id, event_id, recommendation, options, confidence, policy_version) "
                     "values (%s, %s, %s, 'MONITOR', '[]', 0.5, 'competitor-v1') returning id", (cid, org["org"], eid)).fetchone()[0]
    act_as(org["viewer"])
    assert db.execute("select count(*) from competitor_events where competitor_id = %s", (cid,)).fetchone()[0] == 1
    act_as(org["outsider"])
    assert db.execute("select count(*) from competitor_events where competitor_id = %s", (cid,)).fetchone()[0] == 0
    as_admin()
    assert "permission denied" in as_user(db, act_as, as_admin, org["owner"],
                                          "select * from record_competitor_event(%s, null, 'OFFER_CHANGE', 'fake', '{}', null, null, null, 'k2', 1)", (cid,))[0]
    assert "permission denied" in as_user(db, act_as, as_admin, org["owner"], "update competitor_events set summary = 'edited' where id = %s", (eid,))[0]
    assert "permission denied" in as_user(db, act_as, as_admin, org["owner"], "select count(*) from competitor_snapshots", ())[0]
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, org["viewer"],
                                                          "select decide_competitor_insight(%s, 'acted', 'x')", (iid,))[0]
    assert as_user(db, act_as, as_admin, org["marketer"], "select decide_competitor_insight(%s, 'acted', 'Ran a value ad')", (iid,))[0] == "ok"
    assert db.execute("select status, note from competitor_insights where id = %s", (iid,)).fetchone() == ("acted", "Ran a value ad")
