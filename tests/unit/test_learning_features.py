import json

import numpy as np
import pytest

from src.capabilities import focus_group
from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.graph.nodes import focus_group as focus_group_node_module
from src.tools import bandit


def _persona(name: str, **kw) -> Persona:
    base = dict(
        name=name, demographics="34, Pune", psychographics="busy", channel_fit="email", messaging_angle="saves time",
        age_bracket="25-34", income_tier="mid", archetype="teacher", gender="female",
    )
    return Persona(**{**base, **kw})


CREATIVE = Creative(copy_text="Plan lessons in minutes.", image_prompt="a tidy desk", image_bytes=b"", image_style="minimalist", copy_tone="direct_factual", arm_index=0)


class TestFocusGroup:
    def _run(self, monkeypatch, fake_llm, answer, personas):
        monkeypatch.setattr(focus_group, "get_llm", lambda user_id=None: fake_llm(json.dumps(answer)))
        return focus_group.run_focus_group(CREATIVE, personas)

    def test_every_persona_reacts_in_order_with_a_verdict(self, monkeypatch, fake_llm):
        people = [_persona("Maya"), _persona("Ravi", gender="male", archetype="developer"), _persona("Lena")]
        result = self._run(monkeypatch, fake_llm, [
            {"name": "Maya", "reaction": "click", "likelihood": 80, "quote": "I need this."},
            {"name": "Ravi", "reaction": "scroll", "likelihood": 20, "quote": "Not for me."},
            {"name": "Lena", "reaction": "object", "likelihood": 5, "quote": "Too pushy."},
        ], people)
        assert [r.name for r in result.reactions] == ["Maya", "Ravi", "Lena"]
        assert result.reactions[1].archetype == "developer" and result.reactions[1].gender == "male"
        assert result.verdict == {"click": 1, "scroll": 1, "object": 1}
        assert result.average_likelihood == 35

    def test_odd_answers_are_coerced_not_fatal(self, monkeypatch, fake_llm):
        people = [_persona("A"), _persona("B"), _persona("C")]
        result = self._run(monkeypatch, fake_llm, [
            {"reaction": "LOVE IT", "likelihood": 140, "quote": "Yes"},   # off-list reaction, out-of-range score
            {"reaction": "click", "likelihood": "lots"},                  # non-numeric likelihood
        ], people)                                                         # and one answer missing entirely
        assert result.reactions[0].reaction == "click" and result.reactions[0].likelihood == 100
        assert result.reactions[1].likelihood == 0
        assert result.reactions[2].reaction == "scroll" and result.reactions[2].quote == ""

    def test_node_never_blocks_the_gate(self, monkeypatch):
        def boom(_):
            raise RuntimeError("db down")

        monkeypatch.setattr(focus_group_node_module, "get_personas", boom)
        assert focus_group_node_module.focus_group_node({"campaign_id": "c", "user_id": "u", "round_id": 1, "creative": CREATIVE}) == {}


class TestExplainChoice:
    def _arms(self, learned: int | None = None, pulls: int = 0, reward: float = 0.0):
        dim = bandit.CONTEXT_DIM
        rows = []
        for i, (style, tone) in enumerate(bandit.ARMS):
            a, b = np.eye(dim), np.zeros(dim)
            if i == learned:
                x = bandit.build_context_vector("25-34", "mid", "email", "education")
                for _ in range(pulls):
                    a = a + np.outer(x, x)
                    b = b + reward * x
            rows.append({"arm_index": i, "image_style": style, "copy_tone": tone, "a_matrix": a.tolist(), "b_vector": b.tolist(),
                         "pulls": pulls if i == learned else 0, "total_reward": reward * pulls if i == learned else 0})
        return rows

    def test_a_proven_arm_is_exploiting_with_its_track_record(self, monkeypatch):
        monkeypatch.setattr(bandit, "_get_all_arms", lambda: self._arms(learned=3, pulls=30, reward=0.8))
        out = bandit.explain_choice("25-34", "mid", "education", ["email"], 3)
        assert out["mode"] == "exploit" and out["rank"] == 1
        assert out["chosen"]["pulls"] == 30 and out["chosen"]["mean_reward"] == pytest.approx(0.8)
        assert out["chosen"]["expected"] > out["chosen"]["bonus"]
        assert len(out["alternatives"]) == 3 and out["arms_tried"] == 1 and out["total_rounds"] == 30

    def test_an_untried_arm_is_exploring(self, monkeypatch):
        monkeypatch.setattr(bandit, "_get_all_arms", lambda: self._arms())
        out = bandit.explain_choice("25-34", "mid", "education", ["email", "bluesky"], 7)
        assert out["mode"] == "explore"
        assert out["chosen"]["expected"] == 0 and out["chosen"]["mean_reward"] is None
