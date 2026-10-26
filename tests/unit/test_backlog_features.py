"""Compliance radar, Bayesian A/B early stop, market-moment alerts and playbooks."""
import json
from types import SimpleNamespace

import pytest

from src.capabilities import playbooks
from src.capabilities.creative import Creative
from src.capabilities.experiments import bayesian_ab
from src.capabilities.guardrails import check_creative, flesch_reading_ease
from src.capabilities.metrics import MetricsResult
from src.graph.nodes import creative as creative_node_module
from src.graph.nodes import metrics_collector
from src.scheduler import market_watch


class FakeQuery:
    """Just enough of the Supabase query builder: every filter returns itself."""

    def __init__(self, rows, sink=None):
        self.rows, self.sink = rows, sink

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def upsert(self, row, **_):
        if self.sink is not None:
            self.sink.append(row)
        return FakeQuery([row])

    def execute(self):
        return SimpleNamespace(data=self.rows)


class FakeClient:
    def __init__(self, tables, sink=None):
        self.tables, self.sink = tables, sink

    def table(self, name):
        return FakeQuery(self.tables.get(name, []), self.sink)


def _creative(arm=3, style="minimalist", tone="humorous"):
    return Creative(copy_text="x", image_prompt="y", image_bytes=b"", image_style=style, copy_tone=tone, arm_index=arm)


class TestComplianceRadar:
    def test_clean_plain_copy_has_no_findings(self):
        assert check_creative("Plan your week in ten minutes. Try it free today.").issues == []

    def test_every_finding_has_an_area_and_a_fix(self):
        text = "The best app EVER 🚀🚀🔥💸 #budgetingapp guaranteed savings"
        issues = check_creative(text, domain_category="finance_fintech").issues
        codes = {i.code for i in issues}
        assert {"comparative", "all_caps", "emoji_overload", "hashtag_case", "claim"} <= codes
        assert all(i.fix for i in issues) and all(i.severity == "review" for i in issues)
        assert {i.category for i in issues} == {"claims", "accessibility"}

    def test_blocking_checks_keep_blocking_and_now_suggest_fixes(self):
        result = check_creative("Email me at a@b.co", cta_url="https://mine.app")
        assert result.blocked and result.blocked[0].fix and result.blocked[0].category == "safety"

    def test_readability_is_english_only(self):
        dense = ("Notwithstanding considerable organisational complexities, comprehensive financial administration "
                 "necessitates sophisticated multidimensional infrastructural capabilities for contemporary professionals.")
        assert any(i.code == "hard_to_read" for i in check_creative(dense).issues)
        assert not any(i.category == "readability" for i in check_creative(dense, language="es").issues)

    def test_reading_ease_scores_simple_copy_as_easy(self):
        assert flesch_reading_ease("Save time every week. Plan your lessons in minutes, not hours. Try it free today.") > 60


class TestBayesianAB:
    def test_clear_difference_is_decided(self):
        out = bayesian_ab(5, 100, 15, 100)
        assert out["decided"] == "b" and out["prob_b_beats_a"] > 0.95
        assert out["interval"][0] > 0  # the whole 95% interval favours B

    def test_reversed_difference_decides_a(self):
        assert bayesian_ab(15, 100, 5, 100)["decided"] == "a"

    def test_a_tie_is_not_called(self):
        out = bayesian_ab(10, 100, 10, 100)
        assert out["decided"] is None and 0.4 < out["prob_b_beats_a"] < 0.6

    def test_small_samples_are_never_called(self):
        out = bayesian_ab(0, 5, 4, 5)
        assert out["prob_b_beats_a"] > 0.95 and out["decided"] is None

    def test_degenerate_inputs(self):
        assert bayesian_ab(0, 0, 3, 10)["prob_b_beats_a"] is None
        assert bayesian_ab(50, 10, 5, 10)["prob_b_beats_a"] is not None  # clicks above recipients are clamped


class TestEarlyStop:
    @pytest.fixture(autouse=True)
    def offline(self, monkeypatch):
        # The node also checks creative fatigue and a running experiment: both read the database.
        monkeypatch.setattr("src.capabilities.fatigue.run", lambda campaign_id: None)
        monkeypatch.setattr(metrics_collector, "_fixed_horizon", lambda campaign_id: False)

    def test_a_decided_test_stops_the_split_and_promotes_the_winner(self, monkeypatch):
        bayes = {"decided": "b", "prob_b_beats_a": 0.97}
        monkeypatch.setattr(metrics_collector, "collect_metrics", lambda *a, **k: MetricsResult(
            channel_rewards={"email": 0.05, "email_b": 0.15}, overall_reward=0.1,
            raw={"email_b": {"ab_test": {"bayes": bayes}}}))
        updates = {}
        monkeypatch.setattr(metrics_collector, "update_campaign", lambda cid, **f: updates.update(f))
        monkeypatch.setattr(metrics_collector, "_announce", lambda *a: None)
        out = metrics_collector.metrics_collector_node({
            "campaign_id": "c", "user_id": "u", "round_id": 2, "ab_test": True,
            "creative": _creative(1, "minimalist", "direct_factual"), "creative_b": _creative(9, "humor_meme", "humorous"),
        })
        assert out["ab_test"] is False and out["creative_b"] is None
        assert out["promote_arm"] == [9, "humor_meme", "humorous"]
        assert updates["ab_test"] is False and updates["ab_decision"]["winner"] == "b" and updates["ab_decision"]["round"] == 2

    def test_undecided_tests_keep_running(self, monkeypatch):
        monkeypatch.setattr(metrics_collector, "collect_metrics", lambda *a, **k: MetricsResult(
            channel_rewards={}, overall_reward=0, raw={"email_b": {"ab_test": {"bayes": {"decided": None}}}}))
        out = metrics_collector.metrics_collector_node({"campaign_id": "c", "user_id": "u", "round_id": 1, "ab_test": True})
        assert set(out) == {"metrics_result"}

    def test_next_round_uses_the_promoted_arm_once(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(creative_node_module, "generate_creative", lambda *a, **k: seen.update(k) or _creative())
        monkeypatch.setattr(creative_node_module, "brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr(creative_node_module, "playbook_section_for_campaign", lambda cid: "")
        out = creative_node_module.creative_node({
            "idea": "i", "primary_persona": None, "domain_category": "education", "promote_arm": [9, "humor_meme", "humorous"],
        })
        assert seen["arm"] == (9, "humor_meme", "humorous") and out["promote_arm"] is None


class TestMarketMoments:
    def test_spikes_raise_alerts_with_their_numbers(self):
        alerts = market_watch.detect({"trend_mean": 30, "news_total": 8}, {"latest_interest": 72},
                                     {"total_results": 25, "headlines": ["Freelancers flock to budgeting apps"]})
        assert [a["kind"] for a in alerts] == ["trend", "news"]
        assert alerts[0]["detail"]["ratio"] == 2.4 and alerts[1]["detail"]["headline"].startswith("Freelancers")

    def test_ordinary_movement_and_tiny_numbers_are_ignored(self):
        assert market_watch.detect({"trend_mean": 60, "news_total": 40}, {"latest_interest": 70}, {"total_results": 45}) == []
        assert market_watch.detect({"trend_mean": 5, "news_total": 1}, {"latest_interest": 12}, {"total_results": 4}) == []

    def test_missing_signals_never_raise(self):
        assert market_watch.detect({}, None, {"error": "no key"}) == []

    def test_feasibility_saves_the_launch_baseline(self, monkeypatch):
        from src.graph.nodes import feasibility

        saved = {}
        monkeypatch.setattr(feasibility, "update_campaign", lambda cid, **f: saved.update(f))
        feasibility._start_market_watch("c", {"trend": {"keyword": "budget app", "mean_interest": 41}, "news": {"total_results": 12}}, "hi")
        assert saved["market_watch"] == {"keyword": "budget app", "language": "hi",
                                         "baseline": {"trend_mean": 41, "news_total": 12}, "checked_at": None}


class TestPlaybooks:
    TABLES = {
        "campaigns": [{"id": "c1", "idea": "budget app"}, {"id": "c2", "idea": "tax helper"}],
        "iterations": [
            {"campaign_id": "c1", "round_number": 1, "copy_text": "Win back your Sundays.", "image_style": "minimalist", "copy_tone": "humorous", "focus_group": None},
            {"campaign_id": "c1", "round_number": 2, "copy_text": "Act now!", "image_style": "urgency_scarcity", "copy_tone": "urgency_scarcity", "focus_group": None},
            {"campaign_id": "c2", "round_number": 1, "copy_text": "Smile at tax time.", "image_style": "minimalist", "copy_tone": "humorous",
             "focus_group": {"reactions": [{"quote": "Finally, a funny tax app."}]}},
            {"campaign_id": "c2", "round_number": 2, "copy_text": "unmeasured", "image_style": "minimalist", "copy_tone": "humorous", "focus_group": None},
        ],
        "metrics": [
            {"campaign_id": "c1", "round_number": 1, "reward": 0.6}, {"campaign_id": "c1", "round_number": 1, "reward": 0.4},
            {"campaign_id": "c1", "round_number": 2, "reward": 0.1}, {"campaign_id": "c2", "round_number": 1, "reward": 0.7},
        ],
        "feedback": [{"campaign_id": "c1", "round_number": 2, "revision_directive": {"reasoning": "Urgency fell flat."}}],
    }

    def test_gather_computes_the_numbers_itself(self, monkeypatch):
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: FakeClient(self.TABLES))
        data = playbooks.gather("org", "finance_fintech")
        stats = data["stats"]
        assert stats["rounds"] == 3 and stats["campaigns"] == 2  # the unmeasured round is left out
        assert stats["tones"][0] == {"name": "humorous", "mean": 0.6, "n": 2}
        assert data["best"]["copy_text"] == "Smile at tax time." and data["worst"]["copy_text"] == "Act now!"
        assert "Urgency fell flat." in data["notes"] and "Finally, a funny tax app." in data["notes"]

    def test_too_little_data_writes_nothing(self, monkeypatch):
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: FakeClient({"campaigns": [{"id": "c1"}]}))
        assert playbooks.write_playbook("org", "education") is None

    def test_write_saves_a_clean_playbook(self, monkeypatch, fake_llm):
        saved = []
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: FakeClient(self.TABLES, saved))
        monkeypatch.setattr(playbooks, "get_llm", lambda user_id=None: fake_llm(json.dumps({
            "headline": "Humour beats urgency here.", "do": ["Lead with a joke", "", "Keep it short"], "avoid": "Countdown pressure",
            "audience": ["Freelancers"], "next_test": "Try humour with testimonial visuals.",
        })))
        row = playbooks.write_playbook("org", "finance_fintech")
        assert saved and row["content"]["do"] == ["Lead with a joke", "Keep it short"]
        assert row["content"]["avoid"] == ["Countdown pressure"] and row["stats"]["rounds"] == 3

    def test_creatives_get_the_playbook_as_fenced_data(self, monkeypatch):
        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: FakeClient({
            "campaigns": {"org_id": "org", "domain_category": "finance_fintech"},
            "playbooks": {"content": {"headline": "Humour wins", "do": ["Lead with a joke"], "avoid": ["Urgency"]}, "stats": {"rounds": 3}},
        }))
        section = playbooks.playbook_section_for_campaign("c1")
        assert "3 measured rounds" in section and "Do: Lead with a joke" in section and "Avoid: Urgency" in section

    def test_no_playbook_is_an_empty_section(self, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("src.db.supabase_client.get_client", boom)
        assert playbooks.playbook_section_for_campaign("c1") == "" and playbooks.playbook_section_for_campaign(None) == ""

    def test_refresh_never_raises(self, monkeypatch):
        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr("src.db.supabase_client.get_client", boom)
        playbooks.refresh_after_campaign("c1")
