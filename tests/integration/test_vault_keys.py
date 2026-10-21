"""BYOK keys in Supabase Vault: stored and read only through service-role functions."""
import pytest

psycopg = pytest.importorskip("psycopg")


def store(db, user, capability="llm", key="sk-test-abcdef1234"):
    return db.execute("select store_provider_key(%s, %s, %s)", (user, capability, key)).fetchone()[0]


def read(db, user, capability="llm"):
    return db.execute("select read_provider_key(%s, %s)", (user, capability)).fetchone()[0]


def test_round_trip_through_vault_without_plaintext_in_the_table(db, new_user):
    user = new_user()
    assert store(db, user) == "****1234"
    assert read(db, user) == "sk-test-abcdef1234"
    row = db.execute("select encrypted_key, vault_secret_id, masked_key from provider_keys where user_id = %s", (user,)).fetchone()
    assert row[0] is None and row[1] is not None and row[2] == "****1234"
    raw = db.execute("select secret from vault.secrets where id = %s", (row[1],)).fetchone()[0]
    assert "sk-test-abcdef1234" not in raw  # encrypted at rest


def test_rotation_reuses_the_secret(db, new_user):
    user = new_user()
    store(db, user, key="sk-old-11111111")
    first = db.execute("select vault_secret_id from provider_keys where user_id = %s", (user,)).fetchone()[0]
    assert store(db, user, key="sk-new-22222222") == "****2222"
    assert read(db, user) == "sk-new-22222222"
    assert db.execute("select vault_secret_id from provider_keys where user_id = %s", (user,)).fetchone()[0] == first


def test_deleting_the_key_deletes_the_secret(db, new_user, act_as):
    user = new_user()
    store(db, user)
    secret = db.execute("select vault_secret_id from provider_keys where user_id = %s", (user,)).fetchone()[0]
    act_as(user)
    assert db.execute("delete from provider_keys where user_id = %s", (user,)).rowcount == 1
    db.execute("reset role")
    assert db.execute("select count(*) from vault.secrets where id = %s", (secret,)).fetchone()[0] == 0


def test_users_cannot_repoint_their_row_at_someone_elses_secret(db, new_user, act_as):
    victim, attacker = new_user(), new_user()
    store(db, victim, key="sk-victim-99999999")
    store(db, attacker, key="sk-attacker-00000000")
    victim_secret = db.execute("select vault_secret_id from provider_keys where user_id = %s", (victim,)).fetchone()[0]
    act_as(attacker)
    updated = db.execute(
        "update provider_keys set vault_secret_id = %s where user_id = %s", (victim_secret, attacker)
    ).rowcount
    assert updated == 0  # no UPDATE policy for users any more
    db.execute("reset role")
    assert read(db, attacker) == "sk-attacker-00000000"


def test_users_cannot_call_the_key_functions(db, new_user, act_as):
    user = new_user()
    store(db, user)
    act_as(user)
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        read(db, user)
    db.execute("rollback to savepoint s")
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        store(db, user)


def test_service_role_can(db, new_user):
    user = new_user()
    db.execute("set local role service_role")
    assert store(db, user, capability="image") == "****1234"
    assert read(db, user, capability="image") == "sk-test-abcdef1234"


def test_invalid_input_is_rejected(db, new_user):
    user = new_user()
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.RaiseException, match="capability"):
        store(db, user, capability="email")
    db.execute("rollback to savepoint s")
    with pytest.raises(psycopg.errors.RaiseException, match="too short"):
        store(db, user, key="abc")
