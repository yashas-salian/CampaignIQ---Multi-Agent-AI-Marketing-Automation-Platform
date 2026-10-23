"""Model card, bandit lockdown, focus group / arm explanation columns and persona chats, against a real Postgres."""
import pytest

psycopg = pytest.importorskip("psycopg")


def test_model_card_reads_versions_deployment_and_correction_counts(db, new_user, act_as):
    act_as(new_user())
    card = db.execute("select public.model_card()").fetchone()[0]
    v1 = next(v for v in card["versions"] if v["version"] == "v1")
    assert v1["metrics"]["golden"] == pytest.approx(0.8333) and v1["baseline_metrics"]["golden"] == pytest.approx(0.5556)
    assert set(card["corrections"]) == {"total", "since_last_training", "last_30_days"}
    assert card["deployment"]["mode"] in ("off", "shadow", "canary")


def test_model_card_is_for_signed_in_members_only(db, act_as):
    act_as(None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select public.model_card()")


def test_bandit_arms_are_read_only_for_members_and_hidden_from_anon(db, new_user, act_as, as_admin):
    db.execute(
        "insert into bandit_arms (arm_index, image_style, copy_tone, a_matrix, b_vector) "
        "values (999, 'x', 'y', '[]', '[]') on conflict (arm_index) do nothing"
    )
    act_as(new_user())
    assert db.execute("select count(*) from bandit_arms where arm_index = 999").fetchone()[0] == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update bandit_arms set pulls = 1000 where arm_index = 999")
    db.execute("rollback")


def test_anon_cannot_touch_bandit_arms(db, act_as):
    act_as(None)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("select * from bandit_arms")


def test_iterations_carry_focus_group_and_arm_explanation(db):
    cols = {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'iterations'")}
    assert {"focus_group", "arm_explain"} <= cols


def test_persona_chats_are_private_and_only_written_by_the_service(db, new_user, act_as, as_admin):
    alice, bob = new_user(), new_user()
    ref = "persona:00000000-0000-0000-0000-000000000001"
    db.execute("insert into persona_chats (user_id, persona_ref, role, content) values (%s, %s, 'user', 'Would you buy it?')", (alice, ref))
    act_as(bob)
    assert db.execute("select count(*) from persona_chats").fetchone()[0] == 0
    act_as(alice)
    assert db.execute("select content from persona_chats").fetchone()[0] == "Would you buy it?"
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("insert into persona_chats (user_id, persona_ref, role, content) values (%s, %s, 'assistant', 'forged')", (alice, ref))


def test_persona_chat_refs_are_validated(db, new_user):
    alice = new_user()
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into persona_chats (user_id, persona_ref, role, content) values (%s, 'anything', 'user', 'x')", (alice,))
