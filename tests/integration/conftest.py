"""Helpers for tests against the local Supabase Postgres (supabase db start).

Each test runs inside a transaction that is rolled back, impersonating users
the way PostgREST does: `role authenticated` + `request.jwt.claims`.
"""
import json
import os
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


def pytest_collection_modifyitems(items):
    for item in items:
        if "tests/integration" in str(item.path).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def db():
    try:
        conn = psycopg.connect(DB_URL, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("local Supabase Postgres not running (supabase db start)")
    conn.autocommit = False
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def new_user(db):
    def make() -> str:
        user_id = str(uuid.uuid4())
        db.execute(
            "insert into auth.users (id, instance_id, aud, role, email) "
            "values (%s, '00000000-0000-0000-0000-000000000000', 'authenticated', 'authenticated', %s)",
            (user_id, f"{user_id}@test.local"),
        )
        return user_id

    return make


@pytest.fixture
def act_as(db):
    def switch(user_id: str | None) -> None:
        db.execute("set local role " + ("authenticated" if user_id else "anon"))
        claims = {"sub": user_id, "role": "authenticated"} if user_id else {"role": "anon"}
        db.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))

    return switch


@pytest.fixture
def as_admin(db):
    def reset() -> None:
        # Back to a worker-like session: no role switch, no user claims.
        db.execute("reset role")
        db.execute("select set_config('request.jwt.claims', '', true)")

    return reset
