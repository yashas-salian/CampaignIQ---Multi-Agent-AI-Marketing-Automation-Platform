"""The delivery ledger's atomic claim (claim_delivery), on real Postgres."""
import os
import threading

import pytest
from psycopg.types.json import Jsonb

psycopg = pytest.importorskip("psycopg")

DB_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")


def claim(db, campaign="c1", round_id=1, channel="email", user=None):
    return db.execute(
        "select verdict, attempts, note from claim_delivery(%s, %s, %s, %s, %s)",
        (campaign, round_id, channel, user, Jsonb({"to": ["a@x.io"]})),
    ).fetchone()


def finish(db, status):
    db.execute("update deliveries set status = %s where campaign_id = 'c1'", (status,))


def test_first_claim_wins_then_in_flight(db):
    assert claim(db) == ("go", 1, None)
    assert claim(db)[0] == "done" and "another worker" in claim(db)[2]


def test_sent_is_never_claimed_again(db):
    claim(db)
    finish(db, "sent")
    assert claim(db) == ("done", 1, "skipped: already sent for this campaign/round")


def test_failed_can_be_reclaimed_and_counts_attempts(db):
    claim(db)
    finish(db, "failed")
    assert claim(db) == ("go", 2, None)


def test_dead_letters_stay_dead(db):
    claim(db)
    db.execute("update deliveries set status = 'dead', last_error = 'timeout' where campaign_id = 'c1'")
    verdict, _, note = claim(db)
    assert verdict == "done" and note.startswith("dead: gave up after 1 attempts (timeout)")


def test_a_crashed_worker_is_taken_over_after_the_stale_window(db):
    claim(db)
    db.execute("update deliveries set updated_at = now() - interval '1 hour' where campaign_id = 'c1'")
    assert claim(db)[0] == "go"


def test_workers_can_call_it_but_users_cannot(db, new_user, act_as, as_admin):
    db.execute("set local role service_role")
    assert claim(db, campaign="c2")[0] == "go"
    assert db.execute("select feature_enabled_for('x', null)").fetchone()[0] is False
    as_admin()
    act_as(new_user())
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        claim(db, campaign="c3")


def test_concurrent_claims_have_exactly_one_winner():
    """Two separate connections race for the same delivery: one 'go'."""
    key = f"race-{threading.get_ident()}"
    results, barrier = [], threading.Barrier(4)

    def worker():
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            barrier.wait()
            results.append(conn.execute(
                "select verdict from claim_delivery(%s, 1, 'bluesky', null, '{}'::jsonb)", (key,)
            ).fetchone()[0])

    try:
        psycopg.connect(DB_URL, connect_timeout=3).close()
    except psycopg.OperationalError:
        pytest.skip("local Supabase Postgres not running")
    threads = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    try:
        assert sorted(results) == ["done", "done", "done", "go"]
    finally:
        with psycopg.connect(DB_URL, autocommit=True) as conn:
            conn.execute("delete from deliveries where campaign_id = %s", (key,))
