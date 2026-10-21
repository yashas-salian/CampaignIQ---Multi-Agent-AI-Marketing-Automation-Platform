import contextlib

import pytest

from src import observability
from src.providers.gateway import LLMGateway, reset_bench


class FakeObs:
    def __init__(self, kwargs):
        self.kwargs, self.updates = kwargs, []

    def update(self, **kw):
        self.updates.append(kw)


class FakeLangfuse:
    def __init__(self):
        self.observations: list[FakeObs] = []

    def start_as_current_observation(self, **kwargs):
        obs = FakeObs(kwargs)
        self.observations.append(obs)

        @contextlib.contextmanager
        def cm():
            yield obs

        return cm()

    def flush(self):
        pass


class Provider:
    name, model = "groq", "gpt-oss-120b"

    def __init__(self, fail=False):
        self.fail = fail

    def generate(self, prompt, *, system=None):
        if self.fail:
            raise TimeoutError("slow")
        self.last_usage = type("U", (), {"prompt_tokens": 120, "completion_tokens": 30})()
        return "answer"


@pytest.fixture
def lf(monkeypatch):
    fake = FakeLangfuse()
    monkeypatch.setattr(observability, "_langfuse", fake)
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: (_ for _ in ()).throw(KeyError("no db")))
    reset_bench()
    yield fake
    reset_bench()


def test_without_langfuse_everything_is_a_noop(monkeypatch):
    monkeypatch.setattr(observability, "_langfuse", None)
    with observability.span("x") as s:
        s.update(level="ERROR")
    with observability.generation("groq", "m", prompt="p", system=None) as g:
        g.done("t", None)


def test_llm_calls_become_generations_without_prompt_text(lf):
    LLMGateway([Provider()], user_id="u1").generate("secret customer idea", system="sys")
    obs = lf.observations[0]
    assert obs.kwargs["as_type"] == "generation" and obs.kwargs["model"] == "gpt-oss-120b"
    assert obs.kwargs["input"] is None  # content capture is opt-in
    assert obs.kwargs["metadata"]["user_id"] == "u1"
    assert obs.updates[-1] == {"output": None, "usage_details": {"input": 120, "output": 30}}


def test_content_capture_is_opt_in(lf, monkeypatch):
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    LLMGateway([Provider()]).generate("idea", system="sys")
    assert lf.observations[0].kwargs["input"] == {"system": "sys", "prompt": "idea"}
    assert lf.observations[0].updates[-1]["output"] == "answer"


def test_failures_and_fallbacks_are_visible(lf):
    LLMGateway([Provider(fail=True), Provider()]).generate("p")
    first, second = lf.observations
    assert first.updates[-1]["level"] == "ERROR" and "TimeoutError" in first.updates[-1]["status_message"]
    assert second.kwargs["metadata"]["fallback"] is True


def test_graph_nodes_are_spans_and_gate_pauses_are_not_errors(lf):
    class GraphInterrupt(Exception):
        pass

    def gate(state):
        raise GraphInterrupt()

    with pytest.raises(GraphInterrupt):
        observability.traced_node("gate_1", gate)({"campaign_id": "c1", "round_id": 1})
    obs = lf.observations[0]
    assert obs.kwargs["name"] == "node:gate_1" and obs.kwargs["metadata"] == {"campaign_id": "c1", "round": 1}
    assert obs.updates == [{"status_message": "paused for a human decision"}]


def test_node_errors_are_marked(lf):
    def boom(state):
        raise ValueError("bad")

    with pytest.raises(ValueError):
        observability.traced_node("creative", boom)({})
    assert lf.observations[0].updates[0]["level"] == "ERROR"
