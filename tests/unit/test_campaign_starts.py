"""A campaign shows the moment it's created: the worker fills in the row
create-campaign wrote ("Starting up"), and a start that fails says so."""
import sys
from types import SimpleNamespace

import pytest

from src.db import supabase_client
from src.graph import run_campaign


class Recorder:
    """The Supabase query builder, recording each call; `updated` is what an update returns."""

    def __init__(self, updated):
        self.calls, self.updated = [], updated

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, rec, table):
        self.rec, self.table, self.op, self.payload, self.filters = rec, table, None, None, []

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        self.filters.append((col, f"is {val}"))
        return self

    def execute(self):
        self.rec.calls.append((self.table, self.op, self.payload, self.filters))
        return SimpleNamespace(data=self.rec.updated if self.op == "update" else [self.payload])


ARGS = ("c1", "u1", "Cold drink", "food_beverage", 72, "Strong demand")


def test_the_worker_fills_in_the_row_create_campaign_wrote(monkeypatch):
    rec = Recorder(updated=[{"id": "c1"}])
    monkeypatch.setattr(supabase_client, "get_client", lambda: rec)
    supabase_client.create_campaign(*ARGS, org_id="o1", product_image_path="u1/p.jpg")
    assert len(rec.calls) == 1
    table, op, payload, filters = rec.calls[0]
    assert (table, op) == ("campaigns", "update")
    assert payload["feasibility_score"] == 72 and payload["domain_category"] == "food_beverage"
    # Owner, organisation and idea stay as the user created them.
    assert not {"id", "user_id", "idea", "org_id"} & payload.keys()
    # Only a row that is still starting: never a campaign that's further along.
    assert ("id", "c1") in filters and ("status", "created") in filters and ("feasibility_score", "is null") in filters


def test_a_campaign_started_another_way_is_inserted(monkeypatch):
    rec = Recorder(updated=[])
    monkeypatch.setattr(supabase_client, "get_client", lambda: rec)
    supabase_client.create_campaign(*ARGS, org_id="o1")
    assert [c[1] for c in rec.calls] == ["update", "insert"]
    inserted = rec.calls[1][2]
    assert inserted["id"] == "c1" and inserted["idea"] == "Cold drink" and inserted["org_id"] == "o1"


def test_a_failed_start_is_marked_with_its_reason_only_while_starting(monkeypatch):
    rec = Recorder(updated=[])
    monkeypatch.setattr(supabase_client, "get_client", lambda: rec)
    supabase_client.fail_campaign_start("c1", "Not started: daily AI budget used")
    table, op, payload, filters = rec.calls[0]
    assert (op, payload["status"]) == ("update", "failed") and "budget" in payload["start_error"]
    assert ("status", "created") in filters


@pytest.fixture
def worker(monkeypatch):
    """run_campaign.main with the graph, database and budget faked out."""
    failed = []

    class Checkpointer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def setup(self):
            pass

    monkeypatch.setattr(run_campaign, "_checkpointer", lambda: Checkpointer())
    monkeypatch.setattr(run_campaign, "fail_campaign_start", lambda cid, reason: failed.append((cid, reason)))
    monkeypatch.setattr(run_campaign, "get_campaign", lambda cid: {"status": "awaiting_gate_1"})
    monkeypatch.setattr(run_campaign, "personal_org", lambda uid: "o1")
    monkeypatch.setattr(run_campaign, "use_org", lambda org: None)
    monkeypatch.setattr(run_campaign, "load_dotenv", lambda: None)
    monkeypatch.setenv("RESEND_TEST_TO_EMAIL", "me@example.com")
    monkeypatch.setitem(sys.modules, "src.observability", SimpleNamespace(init=lambda name: None))

    def run(graph, *, budget=None, new_id="c1"):
        monkeypatch.setattr(run_campaign, "build_graph", lambda cp: graph)
        monkeypatch.setattr(run_campaign, "budget_exhausted", lambda org: budget)
        argv = ["run_campaign", "Cold drink", "--user-id", "u1"] + (["--new-campaign-id", new_id] if new_id else [])
        monkeypatch.setattr(sys, "argv", argv)
        run_campaign.main()

    return run, failed


def test_the_run_uses_the_row_create_campaign_wrote(worker):
    run, failed = worker
    seen = []
    run(SimpleNamespace(invoke=lambda state, config: seen.append((state["campaign_id"], config))))
    assert seen[0][0] == "c1" and seen[0][1]["configurable"]["thread_id"] == "c1"
    assert failed == []


def test_a_crash_while_starting_marks_the_campaign_failed_and_still_raises(worker):
    run, failed = worker

    def boom(state, config):
        raise RuntimeError("Groq down")

    with pytest.raises(RuntimeError, match="Groq down"):
        run(SimpleNamespace(invoke=boom))
    assert failed and failed[0][0] == "c1" and "create it again" in failed[0][1]


def test_an_exhausted_budget_fails_the_start_with_the_reason(worker):
    run, failed = worker
    run(SimpleNamespace(invoke=lambda *a: pytest.fail("must not run")), budget="daily AI budget used")
    assert failed == [("c1", "Not started: daily AI budget used")]


def test_without_a_written_row_nothing_is_marked(worker):
    run, failed = worker
    run(SimpleNamespace(invoke=lambda *a: pytest.fail("must not run")), budget="daily AI budget used", new_id=None)
    assert failed == []
