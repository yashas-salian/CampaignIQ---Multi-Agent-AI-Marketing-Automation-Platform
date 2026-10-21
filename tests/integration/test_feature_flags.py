"""The single feature-flag rule (feature_enabled_for), shared by Python and the browser."""
import pytest

psycopg = pytest.importorskip("psycopg")


def flag(db, key, *, enabled=True, percent=100, allow=()):
    db.execute(
        "insert into feature_flags (key, enabled, rollout_percent, allow_user_ids) values (%s, %s, %s, %s)",
        (key, enabled, percent, list(allow)),
    )


def enabled_for(db, key, uid):
    return db.execute("select feature_enabled_for(%s, %s)", (key, uid)).fetchone()[0]


def test_unknown_and_disabled_flags_are_off(db, new_user):
    user = new_user()
    flag(db, "dark_launch", enabled=False, allow=[user])
    assert enabled_for(db, "nope", user) is False
    assert enabled_for(db, "dark_launch", user) is False  # kill switch beats the allow list


def test_allow_list_and_full_rollout(db, new_user):
    insider, other = new_user(), new_user()
    flag(db, "beta", percent=0, allow=[insider])
    flag(db, "ga", percent=100)
    assert enabled_for(db, "beta", insider) is True and enabled_for(db, "beta", other) is False
    assert enabled_for(db, "ga", other) is True


def test_percentage_rollout_is_stable_and_monotonic(db, new_user):
    users = [new_user() for _ in range(200)]
    flag(db, "gradual", percent=30)
    first = {u for u in users if enabled_for(db, "gradual", u)}
    assert first == {u for u in users if enabled_for(db, "gradual", u)}  # same answer every time
    assert 30 < len(first) < 90  # ~30% of 200
    db.execute("update feature_flags set rollout_percent = 60 where key = 'gradual'")
    assert first <= {u for u in users if enabled_for(db, "gradual", u)}  # growing never drops anyone


def test_browser_can_only_ask_about_itself(db, new_user, act_as, as_admin):
    me, someone = new_user(), new_user()
    flag(db, "beta", percent=0, allow=[someone])
    act_as(me)
    assert db.execute("select feature_enabled('beta')").fetchone()[0] is False
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select feature_enabled_for('beta', %s)", (someone,))
    db.execute("rollback to savepoint s")
    as_admin()
    act_as(someone)
    assert db.execute("select feature_enabled('beta')").fetchone()[0] is True


def test_flags_are_read_only_for_users(db, new_user, act_as):
    flag(db, "beta", enabled=False)
    act_as(new_user())
    assert db.execute("update feature_flags set enabled = true where key = 'beta'").rowcount == 0
