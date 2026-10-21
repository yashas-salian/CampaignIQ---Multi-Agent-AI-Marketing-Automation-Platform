"""Stripe billing state → plans (apply_billing)."""
import pytest

psycopg = pytest.importorskip("psycopg")


def plan(db, org):
    return db.execute("select plan from organizations where id = %s", (org,)).fetchone()[0]


def test_personal_org_upgrade_flows_through_the_subscription(db, new_user):
    user = new_user()
    org = db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]
    assert db.execute("select apply_billing(%s, 'cus_1', 'sub_1', 'active', now())", (org,)).fetchone()[0] == "pro"
    assert db.execute("select status from subscriptions where user_id = %s", (user,)).fetchone()[0] == "subscribed"
    assert plan(db, org) == "pro"  # synced by the subscriptions trigger
    db.execute("select apply_billing(%s, null, null, 'canceled', null)", (org,))
    assert plan(db, org) == "free"
    assert db.execute("select stripe_customer_id from org_billing where org_id = %s", (org,)).fetchone()[0] == "cus_1"


def test_team_org_plan_follows_its_subscription(db, new_user, act_as, as_admin):
    owner = new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("select apply_billing(%s, 'cus_2', 'sub_2', 'trialing', now())", (org,))
    assert plan(db, org) == "pro"
    db.execute("select apply_billing(%s, 'cus_2', 'sub_2', 'unpaid', now())", (org,))
    assert plan(db, org) == "free"


def test_only_the_service_role_applies_billing(db, new_user, act_as):
    user = new_user()
    org = db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]
    act_as(user)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select apply_billing(%s, 'c', 's', 'active', now())", (org,))
