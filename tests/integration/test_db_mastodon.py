"""Mastodon as a channel: the iterations column, and the ledger and metrics accept it."""
import pytest

psycopg = pytest.importorskip("psycopg")


def test_iterations_record_the_mastodon_post(db):
    cols = {r[0] for r in db.execute("select column_name from information_schema.columns where table_name = 'iterations'")}
    assert "mastodon_post_url" in cols


def test_ledger_and_metrics_accept_mastodon_only_among_new_channels(db, new_user):
    owner = new_user()
    campaign = db.execute(
        "insert into campaigns (idea, domain_category, user_id) values ('Coffee', 'other', %s) returning id", (owner,)
    ).fetchone()[0]
    db.execute(
        "insert into deliveries (campaign_id, round_number, channel, user_id, payload) values (%s, 1, 'mastodon', %s, '{}')",
        (str(campaign), owner),
    )
    db.execute(
        "insert into metrics (campaign_id, user_id, round_number, channel, raw_metrics, reward)"
        " values (%s, %s, 1, 'mastodon', '{\"likes\": 1}', 0.02)",
        (campaign, owner),
    )
    db.execute("savepoint s")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into metrics (campaign_id, user_id, round_number, channel, raw_metrics, reward)"
            " values (%s, %s, 1, 'twitter', '{}', 0)",
            (campaign, owner),
        )
    db.execute("rollback to savepoint s")
