import pytest

from src.capabilities import idea_intake
from src.providers import gateway, registry
from src.providers.base import LLMProvider
from src.providers.free.openai_compatible import OpenAICompatibleProvider
from src.providers.gateway import AllProvidersFailed, LLMGateway


class ApiError(Exception):
    def __init__(self, status_code, message="error"):
        super().__init__(message)
        self.status_code = status_code


class Scripted(LLMProvider):
    """A provider that replays a script of replies/exceptions."""

    free_tier = True

    def __init__(self, name, *script):
        self.name, self.model, self.script, self.calls = name, f"{name}-model", list(script), 0

    def generate(self, prompt, *, system=None):
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        self.last_usage = type("Usage", (), {"prompt_tokens": 11, "completion_tokens": 7})()
        return step


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    gateway.reset_bench()
    rows = []

    class Table:
        def insert(self, row):
            rows.append(row)
            return self

        def execute(self):
            return None

    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: type("C", (), {"table": lambda self, n: Table()})())
    yield rows
    gateway.reset_bench()


def test_first_healthy_provider_answers(isolated):
    groq, cerebras = Scripted("groq", "hi"), Scripted("cerebras", "unused")
    assert LLMGateway([groq, cerebras], user_id="u1").generate("p") == "hi"
    assert cerebras.calls == 0
    assert isolated == [
        {"user_id": "u1", "org_id": None, "provider": "groq", "model": "groq-model", "prompt_tokens": 11, "completion_tokens": 7,
         "latency_ms": isolated[0]["latency_ms"], "ok": True, "error": None}
    ]


def test_daily_limit_fails_over_and_benches_the_provider(isolated):
    groq = Scripted("groq", ApiError(429, "Rate limit reached on tokens per day (TPD)"))
    cerebras = Scripted("cerebras", "from cerebras")
    gw = LLMGateway([groq, cerebras])
    assert gw.generate("p") == "from cerebras"
    assert gw.generate("p") == "from cerebras"
    assert groq.calls == 1  # benched after the first failure, skipped for the second call
    assert [r["ok"] for r in isolated] == [False, True, True]
    assert gateway._benched_until["groq"] - gateway.time.monotonic() > 3000


def test_per_minute_limit_benches_briefly():
    assert gateway._cooldown_seconds(ApiError(429, "tokens per minute (TPM)")) == 60
    assert gateway._cooldown_seconds(ApiError(503)) == 30
    assert gateway._cooldown_seconds(ApiError(401)) == 3600
    assert gateway._cooldown_seconds(ApiError(400)) == 0
    assert gateway._cooldown_seconds(TimeoutError()) == 30


def test_all_failing_raises_with_every_reason():
    gw = LLMGateway([Scripted("groq", ApiError(429, "TPD")), Scripted("gemini", ApiError(500, "boom"))])
    with pytest.raises(AllProvidersFailed, match="groq: .*TPD.*gemini: .*boom"):
        gw.generate("p")


def test_everything_benched_still_tries_instead_of_failing_blind():
    groq = Scripted("groq", ApiError(429, "TPD"), "recovered")
    gw = LLMGateway([groq])
    with pytest.raises(AllProvidersFailed):
        gw.generate("p")
    assert gw.generate("p") == "recovered"


def test_accounting_failure_never_breaks_a_call(monkeypatch):
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: (_ for _ in ()).throw(KeyError("SUPABASE_URL")))
    assert LLMGateway([Scripted("groq", "ok")]).generate("p") == "ok"


class TestRegistryChain:
    def test_free_tier_is_groq_plus_configured_fallbacks(self, monkeypatch):
        monkeypatch.setenv("CEREBRAS_API_KEY", "c")
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        monkeypatch.setenv("FLAG_LLM_FALLBACK", "true")
        llm = registry.get_llm("u1")
        assert isinstance(llm, LLMGateway) and llm.free_tier
        assert [p.name for p in llm.providers] == ["groq", "cerebras", "gemini"]
        assert llm.providers[0]._client.max_retries == 2  # fail over fast instead of waiting out Groq

    def test_kill_switch_leaves_groq_alone_with_full_retries(self, monkeypatch):
        monkeypatch.setenv("CEREBRAS_API_KEY", "c")
        monkeypatch.setenv("FLAG_LLM_FALLBACK", "false")
        llm = registry.get_llm("u1")
        assert [p.name for p in llm.providers] == ["groq"] and llm.providers[0]._client.max_retries == 8

    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "o")
        monkeypatch.setenv("OPENROUTER_MODEL", "meta/llama:free")
        monkeypatch.setenv("FLAG_LLM_FALLBACK", "true")
        provider = registry.get_llm(None).providers[1]
        assert isinstance(provider, OpenAICompatibleProvider) and provider.model == "meta/llama:free"


def test_local_classifier_still_applies_behind_the_gateway(monkeypatch):
    monkeypatch.setattr(idea_intake, "get_llm", lambda user_id=None: LLMGateway([Scripted("groq", "{}")]))
    monkeypatch.setattr("src.providers.free.local_domain_classifier.classify_domain", lambda idea: "education")
    assert idea_intake.normalize_idea("Tutoring app").domain_category == "education"


def test_usage_is_attributed_to_the_runs_organisation(isolated):
    from src.usage import use_org

    use_org("org-42")
    try:
        LLMGateway([Scripted("groq", "ok")], user_id="u1").generate("p")
    finally:
        use_org(None)
    assert isolated[-1]["org_id"] == "org-42"


def test_budget_check_fails_open(monkeypatch):
    from src import usage

    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: (_ for _ in ()).throw(ConnectionError("db down")))
    assert usage.budget_exhausted("org-1") is None
    assert usage.budget_exhausted(None) is None
