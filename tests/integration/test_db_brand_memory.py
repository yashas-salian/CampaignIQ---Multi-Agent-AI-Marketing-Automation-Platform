"""Brand memory in the database: provenance and review dates on every lesson,
who can add or change what, brand-wide rules only from owners/admins (never the
system), corrections that supersede instead of overwrite, expiry, deletion,
lessons from Gate 2 edits and gate reasons, and tenant isolation."""
import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.types.json import Jsonb  # noqa: E402

ADD = "select add_brand_lesson(%s, %s, %s, %s)"


@pytest.fixture
def orgs(db, new_user, act_as, as_admin):
    owner, marketer, viewer, other_owner = new_user(), new_user(), new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Brewline')").fetchone()[0]
    act_as(other_owner)
    other = db.execute("select create_organization('Other Co')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'marketer'), (%s, %s, 'viewer')",
               (org, marketer, org, viewer))
    cid = db.execute("insert into campaigns (idea, domain_category, user_id, org_id, status, current_round) values "
                     "('Coffee', 'food_beverage', %s, %s, 'awaiting_gate_2', 1) returning id", (owner, org)).fetchone()[0]
    return {"org": org, "other": other, "owner": owner, "marketer": marketer, "viewer": viewer, "other_owner": other_owner, "campaign": cid}


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


def lesson(db, act_as, as_admin, o, user="marketer", scope="context", text="Say good value, never cheap: customers read it as low quality."):
    status, mid = as_user(db, act_as, as_admin, o[user], ADD, (o["org"], "BRAND_PREFERENCE", text, scope))
    assert status == "ok", status
    return mid


def test_every_lesson_has_provenance_and_a_review_date(db, orgs, act_as, as_admin):
    mid = lesson(db, act_as, as_admin, orgs)
    row = db.execute("select author_kind, author_id, status, scope, review_at > now(), created_at from brand_memories where id = %s", (mid,)).fetchone()
    assert row[0] == "person" and str(row[1]) == orgs["marketer"] and row[2] == "active" and row[3] == "context" and row[4]
    assert db.execute("select count(*) from audit_log where action = 'memory.added' and target_id = %s", (str(mid),)).fetchone()[0] == 1


def test_who_can_add_what(db, orgs, act_as, as_admin):
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, orgs["viewer"], ADD,
                                                          (orgs["org"], "CAMPAIGN_LESSON", "Short subject lines worked best.", "context"))[0]
    # A brand-wide rule needs an owner or admin.
    assert "only owners and admins can set a brand-wide rule" in as_user(
        db, act_as, as_admin, orgs["marketer"], ADD, (orgs["org"], "BRAND_PREFERENCE", "Never say cheap in any ad.", "brand"))[0]
    assert lesson(db, act_as, as_admin, orgs, user="owner", scope="brand")
    # Another organisation's members can't write into this one.
    assert "only owners, admins and marketers" in as_user(db, act_as, as_admin, orgs["other_owner"], ADD,
                                                          (orgs["org"], "CAMPAIGN_LESSON", "Inject a lesson elsewhere.", "context"))[0]


def test_the_system_proposes_context_lessons_only(db, orgs, act_as, as_admin):
    mid = db.execute("select propose_brand_lesson(%s, 'FAILED_EXPERIMENT', 'Humorous emails underperformed for coffee.', %s, '{}', %s, %s, 0.6)",
                     (orgs["org"], Jsonb({"domains": ["food_beverage"]}), Jsonb([{"kind": "experiment", "ref": "e1"}]), orgs["campaign"])).fetchone()[0]
    assert db.execute("select status, scope, author_kind, expires_at is not null from brand_memories where id = %s", (mid,)).fetchone() == \
        ("proposed", "context", "system", True)
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.CheckViolation, match="brand_rules_are_human"):
        db.execute("insert into brand_memories (org_id, type, lesson, scope, author_kind, review_at) values "
                   "(%s, 'POLICY_DECISION', 'One campaign failed, so ban it all', 'brand', 'system', now() + interval '1 day')", (orgs["org"],))
    db.execute("rollback to savepoint s")
    assert "permission denied" in as_user(db, act_as, as_admin, orgs["owner"],
                                          "select propose_brand_lesson(%s, 'CAMPAIGN_LESSON', 'xxxxxxxxxxxx', '{}', '{}', '[]', null, 0.5)", (orgs["org"],))[0]
    # A person confirms it before it's used.
    assert as_user(db, act_as, as_admin, orgs["marketer"], "select review_brand_lesson(%s, true, %s)", (mid, "Matches what we saw"))[0] == "ok"
    assert db.execute("select status, reviewed_by is not null from brand_memories where id = %s", (mid,)).fetchone() == ("active", True)


def test_a_correction_supersedes_and_keeps_history(db, orgs, act_as, as_admin):
    mid = lesson(db, act_as, as_admin, orgs)
    fix = "select correct_brand_lesson(%s, %s, 'context', null, null, %s)"
    assert "say what was wrong" in as_user(db, act_as, as_admin, orgs["marketer"], fix, (mid, "Say good value.", "typo"))[0]
    status, new = as_user(db, act_as, as_admin, orgs["marketer"], fix, (mid, "Say good value; avoid cheap and budget.", "Budget also tested badly"))
    assert status == "ok"
    assert db.execute("select status from brand_memories where id = %s", (mid,)).fetchone()[0] == "superseded"
    row = db.execute("select status, supersedes, evidence->-1->>'kind' from brand_memories where id = %s", (new,)).fetchone()
    assert row[0] == "active" and str(row[1]) == str(mid) and row[2] == "correction"
    assert "no longer current" in as_user(db, act_as, as_admin, orgs["marketer"], fix, (mid, "Another edit of the old one", "should fail now"))[0]
    # Turning it into a brand rule needs an owner or admin.
    assert "brand-wide rule" in as_user(db, act_as, as_admin, orgs["marketer"], "select correct_brand_lesson(%s, %s, 'brand', null, null, %s)",
                                        (new, "Never say cheap anywhere.", "It applies to every product"))[0]


def test_expiry_and_deletion(db, orgs, act_as, as_admin):
    mid = lesson(db, act_as, as_admin, orgs)
    as_user(db, act_as, as_admin, orgs["marketer"], "select expire_brand_lesson(%s)", (mid,))
    assert db.execute("select status from brand_memories where id = %s", (mid,)).fetchone()[0] == "expired"
    other = lesson(db, act_as, as_admin, orgs, text="A second lesson that should be deleted.")
    assert "only owners, admins or the lesson's author" in as_user(db, act_as, as_admin, orgs["viewer"], "select delete_brand_lesson(%s)", (other,))[0]
    assert as_user(db, act_as, as_admin, orgs["marketer"], "select delete_brand_lesson(%s)", (other,))[0] == "ok"  # its author
    assert db.execute("select count(*) from brand_memories where id = %s", (other,)).fetchone()[0] == 0
    # The worker retires lessons past their expiry.
    db.execute("update brand_memories set expires_at = now() - interval '1 minute', created_at = now() - interval '1 day' where id = %s",
               (lesson(db, act_as, as_admin, orgs, text="A lesson whose expiry has passed."),))
    assert db.execute("select expire_brand_memories()").fetchone()[0] == 1


def test_tenant_isolation(db, orgs, act_as, as_admin):
    mine = lesson(db, act_as, as_admin, orgs)
    act_as(orgs["other_owner"])
    theirs = db.execute(ADD, (orgs["other"], "BRAND_PREFERENCE", "Say artisan roasted in every ad.", "brand")).fetchone()[0]
    assert db.execute("select count(*) from brand_memories where id = %s", (mine,)).fetchone()[0] == 0  # can't read another org's
    as_admin()
    act_as(orgs["viewer"])
    visible = {r[0] for r in db.execute("select id from brand_memories")}
    assert mine in visible and theirs not in visible
    as_admin()
    for fn, args in (("review_brand_lesson(%s, false)", (mine,)), ("expire_brand_lesson(%s)", (mine,)), ("delete_brand_lesson(%s)", (mine,))):
        assert "only" in as_user(db, act_as, as_admin, orgs["other_owner"], f"select {fn}", args)[0]
    assert "permission denied" in as_user(db, act_as, as_admin, orgs["owner"], "update brand_memories set lesson = 'x' where id = %s", (mine,))[0]


def test_a_material_gate_2_edit_needs_a_reason_and_becomes_a_lesson(db, orgs, act_as, as_admin):
    db.execute("insert into iterations (campaign_id, user_id, round_number, copy_text) values (%s, %s, 1, %s)",
               (orgs["campaign"], orgs["owner"], "Cheap coffee for commuters, ready when you arrive at the station."))
    gid = db.execute("insert into gate_decisions (campaign_id, user_id, gate_number, round_number) values (%s, %s, 2, 1) returning id",
                     (orgs["campaign"], orgs["owner"])).fetchone()[0]
    edit = "select edit_round_copy(%s, 1, 'a', %s, %s, %s)"
    # A small fix needs no reason.
    assert as_user(db, act_as, as_admin, orgs["owner"], edit, (orgs["campaign"], "Cheap coffee for commuters, ready when you arrive at the station!", None, False))[0] == "ok"
    rewrite = "Good-value coffee that's waiting for you the moment you step off the train."
    assert "say why" in as_user(db, act_as, as_admin, orgs["owner"], edit, (orgs["campaign"], rewrite, None, False))[0]
    assert as_user(db, act_as, as_admin, orgs["owner"], edit, (orgs["campaign"], rewrite, "Cheap reads as low quality for our brand", True))[0] == "ok"
    row = db.execute("select status, author_kind, type, evidence->0->>'kind', evidence->0->>'before' like 'Cheap coffee%%' from brand_memories "
                     "where source_campaign_id = %s", (orgs["campaign"],)).fetchone()
    assert row == ("active", "person", "BRAND_PREFERENCE", "copy_edit", True)  # "remember this": active straight away
    # A gate reason becomes a proposed lesson (confirmed by a person later).
    db.execute("insert into gate_approvals (gate_decision_id, user_id, decision, comment) values (%s, %s, 'reject', %s)",
               (gid, orgs["owner"], "Never promise delivery times, we cannot meet them at rush hour"))
    assert db.execute("select status, author_kind from brand_memories where lesson like 'Never promise delivery%%'").fetchone() == ("proposed", "system")
