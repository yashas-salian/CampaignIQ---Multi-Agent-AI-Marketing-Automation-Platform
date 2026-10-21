import numpy as np
import pytest
from langgraph.graph import END

from src.capabilities.preflight import PreflightResult
from src.graph import build_graph as graph
from src.graph.nodes import human_gate
from src.graph.nodes.feedback_correction import route_after_feedback
from src.graph.nodes.preflight import route_after_preflight
from src.tools import bandit


def _arm(index: int, b_scale: float = 0.0) -> dict:
    return {
        "arm_index": index,
        "a_matrix": np.eye(bandit.CONTEXT_DIM).tolist(),
        "b_vector": (np.ones(bandit.CONTEXT_DIM) * b_scale).tolist(),
    }


class TestLinUCB:
    def test_context_vector_is_unit_length_with_bias(self):
        x = bandit.build_context_vector("25-34", "mid", "email", "education")
        assert x.shape == (bandit.CONTEXT_DIM,)
        assert np.linalg.norm(x) == pytest.approx(1.0)
        assert x[-1] > 0  # bias term

    def test_twenty_arms(self):
        assert len(bandit.ARMS) == 20 and len(set(bandit.ARMS)) == 20

    def test_untried_arms_tie_on_exploration_only(self):
        x = bandit.build_context_vector("18-24", "low", "bluesky", "other")
        assert bandit._ucb_score(_arm(0), x) == pytest.approx(bandit.ALPHA)

    def test_selects_the_arm_with_the_best_summed_score(self, monkeypatch):
        arms = [_arm(i) for i in range(20)]
        arms[7] = _arm(7, b_scale=0.5)
        monkeypatch.setattr(bandit, "_get_all_arms", lambda: arms)
        index, style, tone = bandit.select_arm_for_campaign("35-44", "high", "b2b_saas", ["bluesky", "email"])
        assert index == 7 and (style, tone) == bandit.ARMS[7]

    def test_reward_update_raises_that_arms_estimate(self):
        x = bandit.build_context_vector("25-34", "mid", "email", "education")
        arm = _arm(0)
        before = bandit._ucb_score(arm, x)
        arm["a_matrix"] = (np.array(arm["a_matrix"]) + np.outer(x, x)).tolist()
        arm["b_vector"] = (np.array(arm["b_vector"]) + 1.0 * x).tolist()
        theta = np.linalg.inv(arm["a_matrix"]) @ np.array(arm["b_vector"])
        assert theta @ x > 0  # learned a positive expected reward for this context
        assert bandit._ucb_score(arm, x) != pytest.approx(before)


class TestRouting:
    def test_gate_1_reject_ends_the_run(self):
        assert graph.route_after_gate_1({"rejected": True}) == END
        assert graph.route_after_gate_1({"rejected": False}) == "generate_creative"

    def test_gate_2_fans_out_to_active_channels(self, monkeypatch):
        assert graph.route_after_gate_2({"rejected": False}) == ["distribution_bluesky", "distribution_email"]
        monkeypatch.setenv("ENABLE_REDDIT", "true")
        assert "distribution_reddit" in graph.route_after_gate_2({"rejected": False})
        assert graph.route_after_gate_2({"rejected": True}) == [END]

    def test_preflight_retries_until_pass_or_attempt_cap(self):
        failed = PreflightResult(predicted_engagement=20, passed=False, panel_feedback="")
        passed = PreflightResult(predicted_engagement=80, passed=True, panel_feedback="")
        assert route_after_preflight({"preflight": failed, "preflight_attempt": 1}) == "generate_creative"
        assert route_after_preflight({"preflight": failed, "preflight_attempt": 3}) == "gate_2"
        assert route_after_preflight({"preflight": passed, "preflight_attempt": 1}) == "gate_2"

    def test_feedback_loops_or_finalizes(self):
        assert route_after_feedback({"continue_campaign": True}) == "generate_creative"
        assert route_after_feedback({"continue_campaign": False}) == "finalize"

    def test_graph_compiles(self):
        assert graph.build_graph() is not None


class TestGate1:
    PERSONA = {
        "name": "Ava",
        "demographics": "d",
        "psychographics": "p",
        "channel_fit": "email",
        "messaging_angle": "m",
        "age_bracket": "25-34",
        "income_tier": "mid",
    }
    STATE = {"campaign_id": "c1", "user_id": "u1", "round_id": 1, "domain_category": "ecommerce_retail"}

    def _patch(self, monkeypatch, campaign: dict, decision: str = "edit"):
        monkeypatch.setattr(human_gate, "create_pending_gate", lambda *a, **k: None)
        monkeypatch.setattr(human_gate, "update_campaign_status", lambda *a: None)
        monkeypatch.setattr(human_gate, "interrupt", lambda payload: {"decision": decision})
        monkeypatch.setattr(human_gate, "get_campaign", lambda cid: campaign)
        monkeypatch.setattr(human_gate, "get_primary_persona", lambda cid: self.PERSONA)

    def test_corrected_category_reaches_the_bandit(self, monkeypatch):
        self._patch(monkeypatch, {"idea": "Spice kits", "domain_category": "food_beverage"})
        assert human_gate.gate_1_node(self.STATE)["domain_category"] == "food_beverage"

    def test_invalid_category_from_the_db_is_ignored(self, monkeypatch):
        self._patch(monkeypatch, {"idea": "Spice kits", "domain_category": "drop table"})
        assert human_gate.gate_1_node(self.STATE)["domain_category"] == "ecommerce_retail"

    def test_reject(self, monkeypatch):
        self._patch(monkeypatch, {}, decision="reject")
        assert human_gate.gate_1_node(self.STATE) == {"rejected": True}
