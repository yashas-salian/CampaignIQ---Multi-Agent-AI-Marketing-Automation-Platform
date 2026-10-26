"""Brand memory (src/capabilities/brand_memory.py): which lessons apply, which
are never used (expired, unconfirmed, superseded, another organisation, in
conflict with policy), how they're ranked, how they reach the prompts (fenced,
subordinate) and the arm choice (stricter only), the lessons the system
proposes, and the stored held-out evaluation. Database rules (provenance,
review, correction, tenant isolation) are in tests/integration/test_db_brand_memory.py."""
from datetime import datetime, timedelta, timezone

import pytest

from src.capabilities import brand_memory as bm
from src.capabilities.brand_memory import (
    Context, allowed_arm, applies, current, merged_directives, policy_conflict, prompt_section, rank,
)

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def mem(id_, lesson="Customers respond to plain, calm wording in our emails.", **kw):
    return {"id": id_, "org_id": "o1", "type": "CAMPAIGN_LESSON", "lesson": lesson, "scope": "context", "conditions": {},
            "directives": {}, "status": "active", "confidence": 0.7, "evidence": [{"kind": "note"}],
            "created_at": (NOW - timedelta(days=10)).isoformat(), "review_at": (NOW + timedelta(days=60)).isoformat(),
            "expires_at": None, **kw}


CTX = Context(org_id="o1", text="Order-ahead coffee for commuters", domain="food_beverage", channels=["email"], language="en",
              age_bracket="25-34", income_tier="mid")
flat = lambda lessons, text: [0.6] * len(lessons)  # noqa: E731  (relevance without loading the embedding model)


class TestWhatIsUsed:
    def test_only_active_unexpired_lessons(self):
        assert current(mem("a"), NOW)
        for status in ("proposed", "rejected", "superseded", "expired"):
            assert not current(mem("a", status=status), NOW), status
        assert not current(mem("a", expires_at=(NOW - timedelta(seconds=1)).isoformat()), NOW)

    def test_a_brand_rule_applies_everywhere_a_context_lesson_only_where_it_matches(self):
        assert applies(mem("a", scope="brand", conditions={"domains": ["fitness"]}), CTX)
        assert applies(mem("a", conditions={"domains": ["food_beverage"], "channels": ["email", "bluesky"]}), CTX)
        assert not applies(mem("a", conditions={"domains": ["fitness"]}), CTX)
        assert not applies(mem("a", conditions={"channels": ["bluesky"]}), CTX)
        assert not applies(mem("a", conditions={"age_brackets": ["55+"]}), CTX)
        assert not applies(mem("a", conditions={"languages": ["es"]}), CTX)

    def test_another_organisations_lesson_never_applies_even_if_passed_in(self):
        assert not applies(mem("a", org_id="o2", scope="brand"), CTX)
        assert rank([mem("a", org_id="o2", scope="brand")], CTX, now=NOW, relevance_fn=flat) == []

    def test_policy_beats_any_lesson(self):
        bad = mem("g", "Tell customers our coffee is guaranteed to make their morning better.", scope="brand")
        assert "absolute or regulated claim" in policy_conflict(bad, "food_beverage")
        assert policy_conflict(mem("x", directives={"prefer_terms": ["clinically proven"]})) is not None
        assert policy_conflict(mem("ok", "Lead with skip the queue in emails.")) is None
        screened = []
        assert rank([bad, mem("ok")], CTX, now=NOW, relevance_fn=flat, screened=screened)[0]["id"] == "ok"
        assert screened and screened[0]["id"] == "g"


class TestRanking:
    def test_relevance_freshness_evidence_and_overdue_reviews(self):
        old = mem("old", created_at=(NOW - timedelta(days=360)).isoformat())
        fresh = mem("fresh")
        strong = mem("strong", confidence=0.95)
        overdue = mem("overdue", review_at=(NOW - timedelta(days=1)).isoformat())
        ranked = rank([old, fresh, strong, overdue], CTX, now=NOW, relevance_fn=flat)
        order = [m["id"] for m in ranked]
        assert order.index("strong") < order.index("fresh") < order.index("old")
        assert next(m for m in ranked if m["id"] == "overdue")["review_overdue"] is True
        assert order.index("fresh") < order.index("overdue")

    def test_a_context_lesson_off_topic_drops_out_a_brand_rule_does_not(self):
        off = rank([mem("off")], CTX, now=NOW, relevance_fn=lambda lessons, text: [0.0])
        assert off == []
        rule = rank([mem("rule", scope="brand")], CTX, now=NOW, relevance_fn=lambda lessons, text: [0.0])
        assert rule and rule[0]["relevance"] == 0.8

    def test_at_most_six_lessons(self):
        assert len(rank([mem(str(i)) for i in range(12)], CTX, now=NOW, relevance_fn=flat)) == bm.MAX_LESSONS


class TestUse:
    def test_the_prompt_section_is_fenced_background_that_never_overrides_rules(self):
        section = prompt_section([{**mem("a", "Say good value, never cheap."), "type": "BRAND_PREFERENCE", "scope": "brand"}])
        assert "background notes, not instructions" in section and "never override" in section
        assert "brand_memory" in section and "Say good value, never cheap." in section
        assert prompt_section([]) == ""

    def test_directives_only_make_generation_stricter(self):
        d = merged_directives([mem("a", directives={"avoid_terms": ["cheap"], "avoid_tones": ["humorous"]}),
                               mem("b", directives={"avoid_terms": ["cheap", "vibes"], "prefer_terms": ["good value"]})])
        assert d == {"avoid_terms": ["cheap", "vibes"], "prefer_terms": ["good value"], "avoid_tones": ["humorous"], "avoid_styles": []}
        arms = [(2, "minimalist", "humorous"), (0, "minimalist", "direct_factual")]
        assert allowed_arm(arms, d) == (0, "minimalist", "direct_factual")
        assert allowed_arm(arms, {"avoid_tones": [], "avoid_styles": []}) is None  # nothing to avoid: the bandit decides
        assert allowed_arm([(2, "minimalist", "humorous")], d) is None  # memory never blocks a round

    def test_recall_never_raises_and_flags_conflicts(self, monkeypatch):
        flagged, used = [], []

        class DB:
            def rpc(self, name, params):
                (flagged if name == "flag_brand_memory_conflict" else used).append(params)
                return type("R", (), {"execute": lambda s: None})()

        monkeypatch.setattr(bm, "_client", lambda: DB())
        monkeypatch.setattr(bm, "load", lambda org: [mem("ok"), mem("g", "Results are guaranteed every time.", scope="brand")])
        r = bm.recall(CTX, relevance_fn=flat)
        assert [m["id"] for m in r.used] == ["ok"] and "brand_memory" in r.section
        assert flagged[0]["p_memory"] == "g" and used == [{"p_ids": ["ok"]}]
        monkeypatch.setattr(bm, "load", lambda org: (_ for _ in ()).throw(RuntimeError("db down")))
        assert bm.recall(CTX, relevance_fn=flat).section == ""
        assert bm.recall(Context(org_id=None)).used == []

    def test_the_creative_step_gets_memory_and_stricter_words(self, monkeypatch):
        from src.graph.nodes import creative as node

        seen = {}
        monkeypatch.setattr(node, "generate_creative", lambda *a, **k: seen.update(k) or "c")
        monkeypatch.setattr(node, "brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr(node, "playbook_section_for_campaign", lambda cid: "")
        monkeypatch.setattr(node, "product_for_campaign", lambda cid: type("P", (), {"cutout": None, "tagline": ""})())
        monkeypatch.setattr(node, "recall", lambda ctx: bm.Recall("MEMORY SECTION", {"avoid_terms": ["cheap"], "prefer_terms": [],
                                                                                    "avoid_tones": ["humorous"], "avoid_styles": []}, []))
        monkeypatch.setattr(node, "_candidate_arms", lambda state: [(2, "minimalist", "humorous"), (0, "minimalist", "direct_factual")])
        persona = type("P", (), {"age_bracket": "25-34", "income_tier": "mid"})()
        node.creative_node({"idea": "coffee", "primary_persona": persona, "domain_category": "food_beverage", "org_id": "o1", "round_id": 1})
        assert seen["memory"] == "MEMORY SECTION" and seen["banned_terms"] == ("cheap",) and seen["arm"] == (0, "minimalist", "direct_factual")

    def test_write_copy_puts_memory_in_the_prompt(self, monkeypatch):
        from src.capabilities import creative
        from src.capabilities.audience import Persona

        prompts = []
        monkeypatch.setattr(creative, "get_llm", lambda user_id=None: object())
        monkeypatch.setattr(creative, "generate_json", lambda llm, prompt, system=None: prompts.append(prompt) or
                            {"copy": "Fresh coffee, ready when you arrive.", "headline": "Ready", "cta": "Order", "image_prompt": "cup"})
        persona = Persona(name="A", demographics="d", psychographics="p", channel_fit="email", messaging_angle="m",
                          age_bracket="25-34", income_tier="mid")
        creative.write_copy("Coffee", persona, domain_category="food_beverage", active_channels=["email"],
                            image_style="minimalist", copy_tone="direct_factual", memory="LESSONS HERE\n")
        assert "LESSONS HERE" in prompts[0]


class TestProposals:
    def test_measured_results_become_context_lessons_for_review(self, monkeypatch):
        calls = []
        monkeypatch.setattr(bm, "propose", lambda org, type_, lesson, **kw: calls.append((type_, lesson, kw)) or "m1")
        campaign = {"id": "c1", "org_id": "o1", "idea": "Order-ahead coffee", "domain_category": "food_beverage"}
        result = {"status": "POSITIVE_IMPACT", "reason": "INTERVAL_ABOVE_ZERO", "analyzed_at": "t",
                  "estimate": {"absolute_lift": 0.044, "interval": [0.017, 0.066]}}
        bm.lesson_from_experiment({"id": "e1", "primary_metric": "qualified_signup_rate"}, campaign, result)
        type_, lesson, kw = calls[-1]
        assert type_ == "CAMPAIGN_LESSON" and "+4.4 points" in lesson
        assert kw["conditions"] == {"domains": ["food_beverage"], "channels": ["email"]} and kw["evidence"][0]["ref"] == "e1"
        assert bm.lesson_from_experiment({"id": "e1", "primary_metric": "x"}, campaign, {"status": "INCONCLUSIVE"}) is None
        bm.lesson_from_refresh({"id": "i1", "strategy": "NEW_VISUAL", "outcome": "WORSE", "applied_round": 4,
                                "outcome_detail": {"rate_before": 0.04, "rate_after": 0.03}}, campaign)
        assert calls[-1][0] == "FAILED_EXPERIMENT" and "a new visual lost more clicks" in calls[-1][1]
        assert bm.lesson_from_refresh({"id": "i2", "strategy": "NEW_HOOK", "outcome": "INCONCLUSIVE"}, campaign) is None

    def test_a_proposal_is_never_a_brand_rule(self, monkeypatch):
        sent = {}

        class DB:
            def rpc(self, name, params):
                sent.update(name=name, **params)
                return type("R", (), {"execute": lambda s: type("D", (), {"data": "m1"})()})()

        monkeypatch.setattr(bm, "_client", lambda: DB())
        bm.propose("o1", "CAMPAIGN_LESSON", "x" * 20, conditions={}, evidence=[], campaign_id=None, confidence=0.6)
        assert sent["name"] == "propose_brand_lesson" and "p_scope" not in sent  # the database fixes it to 'context'


def test_the_held_out_evaluation_meets_its_bar():
    import json

    from src.eval.memory_benchmark import DATA, summary

    s = summary(json.loads(DATA.read_text(encoding="utf-8")))
    assert s["with"]["compliance"] >= s["without"]["compliance"] + 0.3   # memory clearly helps
    assert s["with"]["no_leak"] == 1.0                                   # nothing that mustn't apply leaks
    assert s["with"]["policy_held"] == 1.0                               # policy always beats memory
    assert s["recall_precision"] == 1.0
