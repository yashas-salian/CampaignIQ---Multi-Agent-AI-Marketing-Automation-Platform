"""AI usage & reliability stats (llm_usage_stats)."""
import pytest

psycopg = pytest.importorskip("psycopg")


def test_stats_per_day_and_provider_for_managers_only(db, new_user, act_as, as_admin):
    owner, viewer = new_user(), new_user()
    act_as(owner)
    org = db.execute("select create_organization('Acme')").fetchone()[0]
    as_admin()
    db.execute("insert into memberships (org_id, user_id, role) values (%s, %s, 'viewer')", (org, viewer))
    for provider, ok, ms in [("groq", True, 800), ("groq", True, 1200), ("groq", False, 30000), ("cerebras", True, 400)]:
        db.execute(
            "insert into llm_usage (org_id, provider, prompt_tokens, completion_tokens, latency_ms, ok) values (%s, %s, 100, 50, %s, %s)",
            (org, provider, ms, ok),
        )
    act_as(owner)
    rows = {r[1]: r for r in db.execute("select * from llm_usage_stats(%s)", (org,)).fetchall()}
    assert rows["groq"][2:5] == (3, 1, 450) and rows["cerebras"][2:4] == (1, 0)
    assert rows["groq"][5] == 1200  # median latency
    as_admin()
    act_as(viewer)
    assert db.execute("select count(*) from llm_usage_stats(%s)", (org,)).fetchone()[0] == 0
