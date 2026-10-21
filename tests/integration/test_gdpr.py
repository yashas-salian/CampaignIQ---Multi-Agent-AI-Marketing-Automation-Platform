"""GDPR: export, erasure and retention, on real Postgres."""
import pytest

psycopg = pytest.importorskip("psycopg")


def campaign(db, user, org=None):
    return db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('Spice kits', 'other', %s, %s) returning id",
        (user, org),
    ).fetchone()[0]


def team(db, act_as, as_admin, owner, *members):
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("update organizations set plan = 'pro' where id = %s", (org,))
    for uid, role in members:
        db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, %s)", (org, uid, role))
    return org


def delete_account(db, user):
    """What the delete-account Edge Function does, in SQL."""
    db.execute("select prepare_account_deletion(%s)", (user,))
    db.execute("delete from auth.users where id = %s", (user,))


def test_export_contains_my_data_and_nothing_else(db, new_user, act_as):
    me, other = new_user(), new_user()
    mine = campaign(db, me)
    theirs = campaign(db, other)
    db.execute("insert into personas (campaign_id, user_id, name, demographics, psychographics, channel_fit, messaging_angle) "
               "values (%s, %s, 'Ava', 'd', 'p', 'c', 'm')", (mine, me))
    db.execute("select store_provider_key(%s, 'llm', 'sk-secret-12345678')", (me,))
    act_as(me)
    data = db.execute("select export_my_data()").fetchone()[0]
    assert data["account"]["id"] == me
    assert [c["id"] for c in data["campaigns"]] == [str(mine)]
    assert str(theirs) not in str(data)
    assert data["campaigns"][0]["personas"][0]["name"] == "Ava"
    assert data["provider_keys"] == [{"capability": "llm", "masked_key": "****5678", "updated_at": data["provider_keys"][0]["updated_at"]}]
    assert "sk-secret" not in str(data)
    assert data["memberships"][0]["personal"] is True


def test_export_needs_a_signed_in_user(db):
    assert db.execute("select export_my_data()").fetchone()[0] is None


def test_deleting_a_solo_account_removes_everything(db, new_user):
    user = new_user()
    cid = campaign(db, user)
    personal = db.execute("select ensure_personal_org(%s)", (user,)).fetchone()[0]
    delete_account(db, user)
    assert db.execute("select count(*) from campaigns where id = %s", (cid,)).fetchone()[0] == 0
    assert db.execute("select count(*) from organizations where id = %s", (personal,)).fetchone()[0] == 0
    assert db.execute("select count(*) from subscriptions where user_id = %s", (user,)).fetchone()[0] == 0


def test_team_campaigns_survive_with_another_owner(db, new_user, act_as, as_admin):
    owner, leaver = new_user(), new_user()
    org = team(db, act_as, as_admin, owner, (leaver, "marketer"))
    cid = campaign(db, leaver, org)
    db.execute("insert into iterations (campaign_id, user_id, round_number) values (%s, %s, 1)", (cid, leaver))
    delete_account(db, leaver)
    assert db.execute("select user_id from campaigns where id = %s", (cid,)).fetchone()[0] == __import__("uuid").UUID(owner)
    assert db.execute("select count(*) from iterations where campaign_id = %s", (cid,)).fetchone()[0] == 1
    assert db.execute("select count(*) from memberships where org_id = %s", (org,)).fetchone()[0] == 1


def test_last_owner_of_a_team_cannot_delete_their_account(db, new_user, act_as, as_admin):
    owner, member = new_user(), new_user()
    team(db, act_as, as_admin, owner, (member, "viewer"))
    act_as(owner)
    assert "only owner" in db.execute("select account_deletion_blocker(%s)", (owner,)).fetchone()[0]
    as_admin()
    with pytest.raises(psycopg.Error, match="only owner"):
        db.execute("select prepare_account_deletion(%s)", (owner,))


def test_users_cannot_delete_other_accounts(db, new_user, act_as):
    victim, attacker = new_user(), new_user()
    act_as(attacker)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select prepare_account_deletion(%s)", (victim,))


def test_deletion_is_audited_by_id_only(db, new_user):
    user = new_user()
    delete_account(db, user)
    row = db.execute("select action, details from audit_log where target_id = %s order by id desc limit 1", (user,)).fetchone()
    assert row == ("account.deleted", {})


def test_retention_prunes_old_operational_data(db, new_user):
    user = new_user()
    db.execute("insert into capability_runs (user_id, capability, created_at) values (%s, 'image', now() - interval '100 days')", (user,))
    db.execute("insert into capability_runs (user_id, capability) values (%s, 'image')", (user,))
    db.execute("insert into deliveries (campaign_id, round_number, channel, status, payload, updated_at) "
               "values ('c-old', 1, 'email', 'sent', '{\"to\": [\"a@x.io\"]}', now() - interval '40 days'), "
               "('c-failed', 1, 'email', 'failed', '{\"to\": [\"a@x.io\"]}', now() - interval '40 days')")
    result = db.execute("select apply_retention()").fetchone()[0]
    assert result["capability_runs"] >= 1 and result["delivery_payloads"] >= 1
    assert db.execute("select count(*) from capability_runs where user_id = %s", (user,)).fetchone()[0] == 1
    payloads = dict(db.execute("select campaign_id, payload from deliveries where campaign_id in ('c-old', 'c-failed')").fetchall())
    assert payloads == {"c-old": {}, "c-failed": {"to": ["a@x.io"]}}  # failed sends keep what they need to retry


def test_status_summary_is_public_and_computes_uptime(db, act_as):
    db.execute("insert into status_checks (component, ok, latency_ms) values ('website', true, 120), ('website', false, 9000), ('website', true, 110)")
    db.execute("set local role anon")
    summary = db.execute("select status_summary()").fetchone()[0]
    site = next(c for c in summary["components"] if c["component"] == "website")
    assert site["ok"] is True and float(site["uptime_24h"]) == 66.67
    assert db.execute("select count(*) from status_checks").fetchone()[0] == 0  # RLS: raw rows stay private
