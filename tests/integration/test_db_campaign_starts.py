"""A campaign shows the moment it's created: create-campaign writes the row
("Starting up", no score yet) and the worker fills it in. A start that never
gets going ends as 'failed' instead of spinning forever."""
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")


def _start(db, owner: str) -> str:
    """What create-campaign writes, with the caller's own JWT."""
    return db.execute(
        "insert into campaigns (idea, user_id, domain_category, status, product_image_path) "
        "values ('Cold drink', %s, 'other', 'created', %s) returning id",
        (owner, f"{owner}/{uuid.uuid4()}.jpg"),
    ).fetchone()[0]


def test_a_member_writes_the_starting_row_and_sees_it_at_once(db, new_user, act_as):
    owner = new_user()
    act_as(owner)
    campaign = _start(db, owner)
    row = db.execute("select status, feasibility_score from campaigns where id = %s", (campaign,)).fetchone()
    assert row == ("created", None)


def test_the_placeholder_category_is_neither_logged_nor_counted_as_a_correction(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    campaign = _start(db, owner)
    as_admin()
    created = db.execute(
        "select details from audit_log where action = 'campaign.created' and target_id = %s", (str(campaign),)
    ).fetchone()[0]
    assert "domain_category" not in created
    # The worker fills it in at feasibility: not a person correcting the category.
    db.execute("update campaigns set domain_category = 'food_beverage', feasibility_score = 72 where id = %s", (campaign,))
    corrections = "select count(*) from audit_log where action = 'campaign.category_corrected' and target_id = %s"
    assert db.execute(corrections, (str(campaign),)).fetchone()[0] == 0
    # A real correction after that still is.
    db.execute("update campaigns set domain_category = 'fitness_wellness' where id = %s", (campaign,))
    assert db.execute(corrections, (str(campaign),)).fetchone()[0] == 1


def test_a_starting_campaign_counts_toward_the_plan_and_a_failed_one_does_not(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    campaign = _start(db, owner)
    org = db.execute("select org_id from campaigns where id = %s", (campaign,)).fetchone()[0]
    as_admin()
    active = "select (public.org_usage_unchecked(%s) -> 'used' ->> 'active_campaigns')::int"
    assert db.execute(active, (org,)).fetchone()[0] == 1
    db.execute("update campaigns set status = 'failed', start_error = 'x' where id = %s", (campaign,))
    assert db.execute(active, (org,)).fetchone()[0] == 0


def test_the_plan_limit_is_enforced_on_the_starting_row(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    for _ in range(3):  # the free plan's 3 a day
        _start(db, owner)
    db.execute("savepoint s")
    with pytest.raises(psycopg.Error, match="usage limit"):
        _start(db, owner)
    db.execute("rollback to savepoint s")


def test_a_failed_start_gives_back_its_place_in_the_daily_allowance(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    first = _start(db, owner)
    _start(db, owner)
    _start(db, owner)
    as_admin()
    db.execute("update campaigns set status = 'failed', start_error = 'x' where id = %s", (first,))
    act_as(owner)
    _start(db, owner)  # the free plan's 3 a day, not counting the one that never ran


def test_stalled_starts_are_marked_failed_and_nothing_else_is(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    stalled, fresh, researched = _start(db, owner), _start(db, owner), _start(db, owner)
    as_admin()
    db.execute("update campaigns set created_at = now() - interval '2 hours' where id in (%s, %s)", (stalled, researched))
    db.execute("update campaigns set feasibility_score = 60 where id = %s", (researched,))
    assert db.execute("select public.fail_stale_campaign_starts()").fetchone()[0] == 1
    status = "select status, start_error from campaigns where id = %s"
    failed = db.execute(status, (stalled,)).fetchone()
    assert failed[0] == "failed" and "didn't finish starting" in failed[1]
    assert db.execute(status, (fresh,)).fetchone()[0] == "created"
    assert db.execute(status, (researched,)).fetchone()[0] == "created"


def test_only_workers_may_fail_stalled_starts(db, new_user, act_as):
    act_as(new_user())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.fail_stale_campaign_starts()")
