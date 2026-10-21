"""Organisations, roles and invitations (RLS + the membership functions)."""
import pytest

psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def team(db, new_user, act_as, as_admin):
    """A team org with one member per role; returns (org_id, {role: user_id}, outsider)."""
    users = {role: new_user() for role in ("owner", "admin", "marketer", "approver", "viewer")}
    outsider = new_user()
    act_as(users["owner"])
    org = db.execute("select create_organization('Acme Marketing')").fetchone()[0]
    as_admin()
    # Plan limits are tested separately; a 5-person team needs more than "free".
    db.execute("update organizations set plan = 'pro' where id = %s", (org,))
    for role, uid in users.items():
        if role != "owner":
            db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, %s)", (org, uid, role))
    return org, users, outsider


def campaign_in(db, org, creator):
    return db.execute(
        "insert into campaigns (idea, domain_category, user_id, org_id) values ('i', 'other', %s, %s) returning id",
        (creator, org),
    ).fetchone()[0]


def attempt(db, sql, params=()):
    """Run as the current role; returns rowcount, or 'denied' on a privilege/raise error."""
    db.execute("savepoint a")
    try:
        count = db.execute(sql, params).rowcount
        db.execute("release savepoint a")
        return count
    except (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException):
        db.execute("rollback to savepoint a")
        return "denied"


def test_every_user_gets_a_personal_org(db, new_user):
    user = new_user()
    rows = db.execute(
        "select o.personal, m.role from memberships m join organizations o on o.id = m.org_id where m.user_id = %s", (user,)
    ).fetchall()
    assert rows == [(True, "owner")]


def test_campaigns_without_an_org_land_in_the_creators_personal_org(db, new_user):
    user = new_user()
    cid = db.execute("insert into campaigns (idea, domain_category, user_id) values ('i', 'other', %s) returning id", (user,)).fetchone()[0]
    personal = db.execute("select org_id from memberships where user_id = %s", (user,)).fetchone()[0]
    assert db.execute("select org_id from campaigns where id = %s", (cid,)).fetchone()[0] == personal


def test_everyone_in_the_org_sees_its_campaigns_and_nobody_else_does(db, team, act_as, as_admin):
    org, users, outsider = team
    cid = campaign_in(db, org, users["marketer"])
    for role, uid in users.items():
        act_as(uid)
        assert db.execute("select count(*) from campaigns where id = %s", (cid,)).fetchone()[0] == 1, role
        as_admin()
    act_as(outsider)
    assert db.execute("select count(*) from campaigns where id = %s", (cid,)).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("role", "can_create", "can_decide"),
    [("owner", True, True), ("admin", True, True), ("marketer", True, False), ("approver", False, True), ("viewer", False, False)],
)
def test_permissions_by_role(db, team, act_as, as_admin, role, can_create, can_decide):
    org, users, _ = team
    cid = campaign_in(db, org, users["owner"])
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number) values (%s, %s, 1) returning id", (cid, users["owner"])
    ).fetchone()[0]
    act_as(users[role])
    created = attempt(
        db, "insert into campaigns (idea, domain_category, user_id, org_id) values ('x', 'other', %s, %s)", (users[role], org)
    )
    assert (created == 1) is can_create
    voted = attempt(db, "insert into gate_approvals (gate_decision_id, decision) values (%s, 'approve')", (gate,))
    assert (voted == 1) is can_decide


def test_marketers_cannot_approve_their_own_campaign(db, team, act_as):
    org, users, _ = team
    cid = campaign_in(db, org, users["marketer"])
    gate = db.execute(
        "insert into gate_decisions (campaign_id, user_id, gate_number) values (%s, %s, 2) returning id", (cid, users["marketer"])
    ).fetchone()[0]
    act_as(users["marketer"])
    assert attempt(db, "insert into gate_approvals (gate_decision_id, decision) values (%s, 'approve')", (gate,)) == "denied"
    assert attempt(db, "update gate_decisions set decision = 'approve' where campaign_id = %s", (cid,)) == 0


def test_outsiders_cannot_create_campaigns_in_the_org(db, team, act_as):
    org, _, outsider = team
    act_as(outsider)
    assert attempt(db, "insert into campaigns (idea, domain_category, user_id, org_id) values ('x', 'other', %s, %s)", (outsider, org)) == "denied"


def test_members_cannot_edit_memberships_directly(db, team, act_as):
    org, users, _ = team
    act_as(users["viewer"])
    assert attempt(db, "update memberships set role = 'owner' where user_id = %s", (users["viewer"],)) == 0
    assert attempt(db, "insert into memberships (org_id, user_id, role) values (%s, %s, 'owner')", (org, users["viewer"])) == "denied"


class TestInvitations:
    def invite(self, db, org, email, role="marketer"):
        return db.execute("select create_invitation(%s, %s, %s)", (org, email, role)).fetchone()[0]

    def email_of(self, db, uid):
        return db.execute("select email from auth.users where id = %s", (uid,)).fetchone()[0]

    def test_invite_and_accept(self, db, team, new_user, act_as, as_admin):
        org, users, _ = team
        newcomer = new_user()
        email = self.email_of(db, newcomer)
        act_as(users["admin"])
        token = self.invite(db, org, email.upper())
        assert db.execute("select token_hash <> %s from invitations where org_id = %s", (token, org)).fetchone()[0]
        as_admin()
        act_as(newcomer)
        assert db.execute("select accept_invitation(%s)", (token,)).fetchone()[0] == org
        assert db.execute("select org_role(%s)", (org,)).fetchone()[0] == "marketer"
        assert attempt(db, "select accept_invitation(%s)", (token,)) == "denied"  # single use

    def test_invite_is_bound_to_its_email(self, db, team, new_user, act_as, as_admin):
        org, users, _ = team
        intended, thief = new_user(), new_user()
        email = self.email_of(db, intended)
        act_as(users["owner"])
        token = self.invite(db, org, email)
        as_admin()
        act_as(thief)
        assert attempt(db, "select accept_invitation(%s)", (token,)) == "denied"

    def test_only_managers_invite_and_only_owners_invite_admins(self, db, team, act_as, as_admin):
        org, users, _ = team
        act_as(users["marketer"])
        assert attempt(db, "select create_invitation(%s, 'x@y.io', 'viewer')", (org,)) == "denied"
        as_admin()
        act_as(users["admin"])
        assert attempt(db, "select create_invitation(%s, 'x@y.io', 'admin')", (org,)) == "denied"

    def test_expired_invites_fail(self, db, team, new_user, act_as, as_admin):
        org, users, _ = team
        newcomer = new_user()
        email = self.email_of(db, newcomer)
        act_as(users["owner"])
        token = self.invite(db, org, email)
        as_admin()
        db.execute("update invitations set expires_at = now() - interval '1 minute' where org_id = %s", (org,))
        act_as(newcomer)
        assert attempt(db, "select accept_invitation(%s)", (token,)) == "denied"


class TestRoleChanges:
    def test_the_last_owner_cannot_leave_or_be_demoted(self, db, team, act_as):
        org, users, _ = team
        act_as(users["owner"])
        assert attempt(db, "select set_member_role(%s, %s, 'admin')", (org, users["owner"])) == "denied"
        assert attempt(db, "select remove_member(%s, %s)", (org, users["owner"])) == "denied"

    def test_admins_cannot_touch_owners_or_make_admins(self, db, team, act_as):
        org, users, _ = team
        act_as(users["admin"])
        assert attempt(db, "select set_member_role(%s, %s, 'viewer')", (org, users["owner"])) == "denied"
        assert attempt(db, "select set_member_role(%s, %s, 'admin')", (org, users["viewer"])) == "denied"
        assert attempt(db, "select set_member_role(%s, %s, 'approver')", (org, users["viewer"])) == 1

    def test_anyone_can_leave(self, db, team, act_as):
        org, users, _ = team
        act_as(users["viewer"])
        db.execute("select remove_member(%s, %s)", (org, users["viewer"]))
        assert db.execute("select org_role(%s)", (org,)).fetchone()[0] is None


def test_member_list_shows_emails_only_to_members(db, team, act_as, as_admin):
    org, users, outsider = team
    act_as(users["viewer"])
    assert len(db.execute("select * from org_members(%s)", (org,)).fetchall()) == 5
    as_admin()
    act_as(outsider)
    assert db.execute("select * from org_members(%s)", (org,)).fetchall() == []


def test_personal_orgs_cannot_invite(db, new_user, act_as):
    user = new_user()
    personal = db.execute("select org_id from memberships where user_id = %s", (user,)).fetchone()[0]
    act_as(user)
    assert attempt(db, "select create_invitation(%s, 'x@y.io', 'viewer')", (personal,)) == "denied"
