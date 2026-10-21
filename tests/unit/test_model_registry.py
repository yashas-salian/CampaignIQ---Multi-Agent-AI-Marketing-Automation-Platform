import pytest

from src.finetune import deployments
from src.providers.free import local_domain_classifier as ldc


@pytest.fixture
def wired(monkeypatch):
    """Active + candidate 'models' that just label differently; records shadow logs."""
    state = {"deployment": {}, "shadow": []}
    monkeypatch.setenv("DOMAIN_CLASSIFIER", "local")
    monkeypatch.setattr(ldc, "available", lambda: True)
    monkeypatch.setattr(ldc, "_deployment", lambda: state["deployment"])
    monkeypatch.setattr(ldc, "_model_path", lambda: "active.gguf")
    monkeypatch.setattr(ldc, "_candidate_path", lambda: "candidate.gguf" if state["deployment"].get("mode") in ("shadow", "canary") else None)
    monkeypatch.setattr(
        "src.finetune.local_classifier.classify",
        lambda idea, path: ("education" if path == "active.gguf" else "healthcare", "x"),
    )
    monkeypatch.setattr(ldc, "_log_shadow", lambda idea, a, c: state["shadow"].append((a, c)))
    return state


def test_default_serves_the_active_model(wired):
    assert ldc.classify_domain("Tutoring app") == "education"
    assert wired["shadow"] == []


def test_shadow_uses_active_but_logs_the_candidate(wired):
    wired["deployment"] = {"mode": "shadow", "candidate_revision": "abc"}
    assert ldc.classify_domain("Tutoring app") == "education"
    assert wired["shadow"] == [("education", "healthcare")]


def test_canary_sends_a_stable_share_to_the_candidate(wired):
    wired["deployment"] = {"mode": "canary", "candidate_revision": "abc", "canary_percent": 30}
    ideas = [f"idea number {i}" for i in range(400)]
    first = [ldc.classify_domain(i) for i in ideas]
    assert first == [ldc.classify_domain(i) for i in ideas]  # same idea, same model
    share = first.count("healthcare") / len(first)
    assert 0.2 < share < 0.4


def test_canary_zero_and_hundred(wired):
    wired["deployment"] = {"mode": "canary", "candidate_revision": "abc", "canary_percent": 0}
    assert ldc.classify_domain("x") == "education"
    wired["deployment"]["canary_percent"] = 100
    assert ldc.classify_domain("x") == "healthcare"


def test_registry_lookup_fails_open(monkeypatch):
    deployments.current.cache_clear()
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: (_ for _ in ()).throw(ConnectionError("db down")))
    assert deployments.current() == {}
    deployments.current.cache_clear()


def test_promotion_keeps_the_previous_revision_for_rollback(monkeypatch):
    updates = []
    monkeypatch.setattr(deployments, "current", lambda: {"active_revision": "old"})
    monkeypatch.setattr(deployments, "_update", lambda **f: updates.append(f))
    deployments.record_promotion("new")
    assert updates == [{"active_revision": "new", "previous_revision": "old", "candidate_revision": None, "mode": "off", "canary_percent": 0}]
