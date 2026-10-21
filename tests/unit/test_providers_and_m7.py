import pytest

from src.finetune import retrain
from src.providers import registry
from src.providers.free import local_domain_classifier as ldc
from src.providers.gateway import LLMGateway
from src.providers.paid.openai_llm import OpenAILLMProvider


class TestProviderRegistry:
    def test_force_free_tier_ignores_byok(self, monkeypatch):
        monkeypatch.setattr(registry, "_byok_key", lambda *a: pytest.fail("must not look up keys"))
        assert isinstance(registry.get_llm("u1"), LLMGateway)

    def test_byok_key_wins_for_that_user(self, monkeypatch):
        monkeypatch.setenv("FORCE_FREE_TIER", "false")
        monkeypatch.setattr(registry, "_byok_key", lambda user_id, capability: "sk-user" if capability == "llm" else None)
        assert isinstance(registry.get_llm("u1"), OpenAILLMProvider)

    def test_unsubscribed_user_without_keys_is_free(self, monkeypatch):
        monkeypatch.setenv("FORCE_FREE_TIER", "false")
        monkeypatch.setenv("PAID_LLM_API_KEY", "sk-ours")
        monkeypatch.setattr(registry, "_byok_key", lambda *a: None)
        monkeypatch.setattr(registry, "_is_subscribed", lambda user_id: False)
        assert isinstance(registry.get_llm("u1"), LLMGateway)

    def test_no_user_context_and_no_paid_key_is_free(self, monkeypatch):
        monkeypatch.setenv("FORCE_FREE_TIER", "false")
        assert isinstance(registry.get_llm(None), LLMGateway)


class TestLocalDomainClassifier:
    @pytest.fixture(autouse=True)
    def _fresh_caches(self):
        ldc._model_path.cache_clear()
        ldc.available.cache_clear()
        yield
        ldc._model_path.cache_clear()
        ldc.available.cache_clear()

    def test_disabled_by_env(self):
        assert ldc.available() is False and ldc.classify_domain("x") is None

    def test_missing_model_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DOMAIN_CLASSIFIER", "local")
        monkeypatch.setattr(ldc, "LOCAL_DIR", tmp_path)
        assert ldc.available() is False and ldc.classify_domain("x") is None


class TestRetrain:
    def test_holdout_split_is_deterministic_and_about_a_fifth(self):
        ids = [f"id-{i}" for i in range(2000)]
        held = [i for i in ids if retrain._is_holdout(i)]
        assert [i for i in ids if retrain._is_holdout(i)] == held
        assert 0.15 < len(held) / len(ids) < 0.25

    @pytest.fixture
    def prep(self, monkeypatch, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        retrain._write_jsonl(data / "train.jsonl", [{"idea": "Spice kits", "label": "ecommerce_retail"}, {"idea": "Yoga", "label": "fitness_wellness"}])
        retrain._write_jsonl(data / "val.jsonl", [{"idea": "v", "label": "other"}])
        monkeypatch.setattr(retrain, "DATA_DIR", data)
        monkeypatch.setattr(retrain, "_current_meta", lambda: {"trained_at": "2026-10-01T00:00:00+00:00"})
        monkeypatch.setattr(retrain, "_is_holdout", lambda row_id: row_id == "held")
        return tmp_path / "out" / "kaggle-data"

    def _corrections(self, monkeypatch, rows):
        monkeypatch.setattr(retrain, "_corrections", lambda: rows)

    def test_skips_below_the_threshold(self, monkeypatch, prep, capsys):
        self._corrections(monkeypatch, [{"id": "a", "idea": "x", "corrected_domain": "other", "created_at": "2026-10-20"}])
        retrain.prepare(prep, force=False)
        assert "should_train=false" in capsys.readouterr().out
        assert not prep.exists()

    def test_old_corrections_dont_count_as_new(self, monkeypatch, prep, capsys):
        rows = [{"id": f"r{i}", "idea": f"i{i}", "corrected_domain": "other", "created_at": "2026-09-01"} for i in range(40)]
        self._corrections(monkeypatch, rows)
        retrain.prepare(prep, force=False)
        assert "should_train=false" in capsys.readouterr().out

    def test_corrections_override_teacher_labels_and_holdout_is_kept_out(self, monkeypatch, prep):
        self._corrections(
            monkeypatch,
            [
                {"id": "fix", "idea": "spice kits", "corrected_domain": "food_beverage", "created_at": "2026-10-20"},
                {"id": "held", "idea": "secret test idea", "corrected_domain": "healthcare", "created_at": "2026-10-20"},
            ],
        )
        retrain.prepare(prep, force=True)
        train = retrain._jsonl(prep / "train.jsonl")
        assert {"idea": "Spice kits", "label": "ecommerce_retail"} not in train  # teacher label replaced
        assert sum(r["idea"] == "spice kits" and r["label"] == "food_beverage" for r in train) == retrain.CORRECTION_WEIGHT
        assert all(r["idea"] != "secret test idea" for r in train)
        assert retrain._jsonl(prep.parent / "corrections_holdout.jsonl") == [{"idea": "secret test idea", "label": "healthcare"}]

    @pytest.mark.parametrize(
        ("cand", "curr", "promote"),
        [
            ((0.83, 0.75), (0.83, 0.75), True),  # ties are promoted
            ((0.83, 0.73), (0.83, 0.75), True),  # within the held-out slack
            ((0.78, 0.90), (0.83, 0.75), False),  # worse on human labels
            ((0.83, 0.70), (0.83, 0.75), False),  # beyond the slack
        ],
    )
    def test_quality_gate(self, monkeypatch, tmp_path, capsys, cand, curr, promote):
        current = tmp_path / "curr.gguf"
        current.write_text("x")
        golden, heldout = [{"idea": "g", "expected_domain": "l"}], [{"idea": "h", "label": "l"}]
        monkeypatch.setattr(retrain, "_jsonl", lambda path: golden if path == retrain.GOLDEN else heldout)
        scores = {"cand.gguf": cand, str(current): curr}
        monkeypatch.setattr(
            retrain, "_accuracy", lambda rows, model: None if not rows else scores[model][0 if rows[0]["idea"] == "g" else 1]
        )
        retrain.evaluate("cand.gguf", str(current), tmp_path / "no-holdout.jsonl", tmp_path / "report.json")
        assert f"promote={str(promote).lower()}" in capsys.readouterr().out

    def test_first_model_is_always_promoted(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(retrain, "_jsonl", lambda path: [{"idea": "g", "expected_domain": "l", "label": "l"}])
        monkeypatch.setattr(retrain, "_accuracy", lambda rows, model: 0.1 if rows else None)
        retrain.evaluate("cand.gguf", None, tmp_path / "none.jsonl", tmp_path / "report.json")
        assert "promote=true" in capsys.readouterr().out


class TestByokKeyLookup:
    class Client:
        def __init__(self, vaulted, legacy):
            self.vaulted, self.legacy, self.calls = vaulted, legacy, []

        def rpc(self, name, params):
            self.calls.append(name)
            return type("Q", (), {"execute": lambda q: type("R", (), {"data": self.vaulted})()})()

        def table(self, name):
            client = self

            class Query:
                def select(self, *a): return self
                def eq(self, *a): return self
                def maybe_single(self): return self
                def execute(self):
                    client.calls.append("legacy")
                    return type("R", (), {"data": {"encrypted_key": client.legacy} if client.legacy else None})()

            return Query()

    def test_vault_first(self, monkeypatch):
        client = self.Client("sk-from-vault", None)
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: client)
        assert registry._byok_key("u1", "llm") == "sk-from-vault" and client.calls == ["read_provider_key"]

    def test_legacy_aes_rows_still_work(self, monkeypatch):
        from src.providers.crypto import encrypt_key

        client = self.Client(None, encrypt_key("sk-legacy-123"))
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: client)
        assert registry._byok_key("u1", "llm") == "sk-legacy-123"

    def test_no_key(self, monkeypatch):
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: self.Client(None, None))
        assert registry._byok_key("u1", "llm") is None
