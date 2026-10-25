"""Decision intelligence (src/capabilities/decision.py): the scenario suite,
the hard-block invariant, evidence handling, the graph step, re-evaluation
of a WAIT, and the destination check. No network, no LLM."""
import copy
from datetime import timedelta

import pytest

from src.capabilities import decision as dmod
from src.capabilities.decision import DECISIONS, DecisionInputs, evaluate, intent_share, reachable
from src.eval.decision_benchmark import run as benchmark
from src.eval.decision_scenarios import FRESH, NOW, SCENARIOS, make

STRONG = dict(trend=(75, 60, True), news=80, intent=(5, 3, 8), history={"campaigns": 4, "mean_reward": 0.12})


class TestScenarioSuite:
    def test_at_least_twenty_fixed_scenarios_covering_every_outcome(self):
        assert len(SCENARIOS) >= 20
        assert {s.expected for s in SCENARIOS} == set(DECISIONS)

    def test_every_decision_is_reproducible(self):
        for s in SCENARIOS:
            assert evaluate(s.inputs, now=NOW).model_dump() == evaluate(copy.deepcopy(s.inputs), now=NOW).model_dump(), s.id

    def test_the_engine_beats_the_launch_if_feasible_baseline(self):
        result = benchmark()
        assert result["engine_accuracy"] >= 0.9
        assert result["engine_accuracy"] > result["baseline_accuracy"]
        assert result["engine_unsafe_launches"] == 0 and result["baseline_unsafe_launches"] > 0
        assert result["engine_weak_launches"] == 0 and result["reproducible"]

    def test_every_hard_block_scenario_is_killed(self):
        for s in SCENARIOS:
            d = evaluate(s.inputs, now=NOW)
            if d.hard_blocks:
                assert d.decision == "KILL" and d.reason_codes[0] == d.hard_blocks[0]["code"], s.id


class TestHardConstraints:
    @pytest.mark.parametrize("idea, code", [
        ("Online store selling pistols", "PROHIBITED_PRODUCT"),
        ("Fake IDs for festival entry", "PROHIBITED_PRODUCT"),
        ("Spyware to read your partner's messages", "PROHIBITED_PRODUCT"),
        ("Supplement that cures cancer naturally", "UNSUPPORTABLE_CLAIM"),
        ("Lose 10 kg in 7 days with our tea", "UNSUPPORTABLE_CLAIM"),
        ("Double your money with crypto signals", "UNSUPPORTABLE_CLAIM"),
    ])
    def test_a_perfect_opportunity_never_overrides_a_hard_block(self, idea, code):
        d = evaluate(make(idea, **STRONG), now=NOW)
        assert d.opportunity_score >= 65  # the market looks great...
        assert d.decision == "KILL" and code in d.reason_codes  # ...and it's blocked anyway

    def test_brand_banned_words_and_a_broken_link_block_too(self):
        assert "BANNED_TERM" in evaluate(make("Cheap sunglasses", banned=["cheap"], **STRONG), now=NOW).reason_codes
        broken = make("Water bottles", destination={"status": "invalid", "detail": "404"}, **STRONG)
        assert evaluate(broken, now=NOW).decision == "KILL"

    def test_claims_that_need_evidence_are_flagged_not_blocked(self):
        d = evaluate(make("Clinically proven sleep mask", **STRONG), now=NOW)
        assert d.decision == "LAUNCH" and d.review_flags and d.review_flags[0]["code"] == "CLAIM_NEEDS_EVIDENCE"

    def test_ordinary_words_are_not_mistaken_for_prohibited_products(self):
        for idea in ("Water guns for summer pool parties", "Glue guns for crafts", "Massage gun for runners",
                     "Dog treats made from salmon"):
            assert not evaluate(make(idea, **STRONG), now=NOW).hard_blocks, idea
        # The block names the exact words that triggered it, so a human can see why.
        assert '"rifles"' in evaluate(make("Hunting rifles online", **STRONG), now=NOW).hard_blocks[0]["detail"]


class TestEvidence:
    def test_missing_signals_raise_uncertainty_instead_of_counting_as_zero(self):
        full = evaluate(make("Water bottles", **STRONG), now=NOW)
        no_trend = evaluate(make("Water bottles", trend_failed=True, news=80, intent=(5, 3, 8),
                                 history={"campaigns": 4, "mean_reward": 0.12}), now=NOW)
        assert no_trend.uncertainty == pytest.approx(full.uncertainty + 0.35)
        demand = next(f for f in no_trend.factors if f.key == "demand")
        assert demand.score is None and not demand.available and "MISSING_DEMAND_DATA" in no_trend.reason_codes
        assert no_trend.decision != "LAUNCH"  # never a full launch without demand data

    def test_stale_evidence_is_named_and_excluded(self):
        old = (NOW - timedelta(days=4)).isoformat()
        d = evaluate(make("Water bottles", fetched=old, **STRONG), now=NOW)
        assert "STALE_EVIDENCE" in d.reason_codes and d.decision == "INSUFFICIENT_EVIDENCE"
        assert all(f.stale for f in d.factors if f.key in ("demand", "competition"))

    def test_too_little_evidence_gives_no_score(self):
        d = evaluate(make("Ice", trend_failed=True, news_failed=True, intent=(0, 0, 2)), now=NOW)
        assert d.decision == "INSUFFICIENT_EVIDENCE" and d.opportunity_score is None

    def test_every_factor_says_where_it_came_from(self):
        for f in evaluate(make("Water bottles", **STRONG), now=NOW).factors:
            assert f.source and f.reliability in ("measured", "proxy", "estimate") and f.value

    def test_purchase_intent_reads_buying_and_comparing_words(self):
        assert intent_share(["Where can I buy it?", "nice weather"], "en") == 0.5
        assert intent_share(["best one?", "lol"], "en") == pytest.approx(0.3)
        assert intent_share(["यह कहाँ से खरीद सकते हैं?", "बारिश"], "hi") == 0.5
        assert intent_share(["¿dónde comprar?", "hola"], "es") == 0.5

    def test_reachability_maps_persona_channels_to_ours(self):
        assert reachable("Email newsletters and LinkedIn", ["bluesky", "email"])
        assert reachable("Twitter/X threads", ["bluesky", "email"])
        assert not reachable("Instagram reels and TikTok", ["bluesky", "email"])

    def test_test_small_caps_the_rounds_and_wait_names_its_trigger(self):
        small = evaluate(make("Merch", trend=(85, 70, True), news=3000, intent=(0, 0, 14)), now=NOW)
        assert small.decision == "TEST_SMALL" and small.constraints == {"max_rounds": 2}
        wait = evaluate(make("Padel grips", trend=(25, 8, True), news=10, intent=(0, 1, 13), reach=(2, 3)), now=NOW)
        assert wait.decision == "WAIT" and wait.reevaluate["type"] == "trend_threshold" and wait.reevaluate["threshold"] >= 30

    def test_the_baseline_is_recorded_for_comparison(self):
        d = evaluate(make("Water bottles", **STRONG), now=NOW)
        assert d.baseline["decision"] in ("LAUNCH", "KILL") and "feasibility" in d.baseline["rule"]
        assert d.requires_human_approval and d.policy_version == dmod.POLICY_VERSION


class TestDestination:
    @pytest.fixture
    def http(self, monkeypatch):
        import requests

        def use(status=None, error=None):
            def call(url, **kw):
                if error:
                    raise error
                return type("R", (), {"status_code": status})()

            monkeypatch.setattr(requests, "head", call)
            monkeypatch.setattr(requests, "get", call)

        return use

    def test_outcomes(self, http):
        import requests

        assert dmod.check_destination(None) is None
        assert dmod.check_destination("ftp://x.io")["status"] == "invalid"
        http(200)
        assert dmod.check_destination("https://shop.example/a")["status"] == "ok"
        http(404)
        assert dmod.check_destination("https://shop.example/a")["status"] == "invalid"
        http(503)
        assert dmod.check_destination("https://shop.example/a")["status"] == "unverified"
        http(error=requests.exceptions.ConnectionError("getaddrinfo failed"))
        assert dmod.check_destination("https://nope.example")["status"] == "invalid"
        http(error=requests.exceptions.Timeout("slow"))
        assert dmod.check_destination("https://slow.example")["status"] == "unverified"


class TestGraphStep:
    @pytest.fixture
    def node(self, monkeypatch):
        from src.graph.nodes import decision as node_mod

        seen = {"status": None, "updates": {}, "saved": []}
        monkeypatch.setattr(node_mod, "get_campaign", lambda cid: {"org_id": "o1", "cta_url": None, "max_rounds": 3})
        monkeypatch.setattr(node_mod, "brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr(node_mod, "update_campaign_status", lambda cid, s: seen.update(status=s))
        monkeypatch.setattr(node_mod, "update_campaign", lambda cid, **f: seen["updates"].update(f))
        monkeypatch.setattr(node_mod, "save", lambda d, i, **k: seen["saved"].append(d.decision))

        def use(inputs: DecisionInputs):
            monkeypatch.setattr(node_mod, "inputs_from", lambda *a, **k: inputs)
            return node_mod.decision_node({"campaign_id": "c1", "user_id": "u1", "idea": inputs.idea}), seen

        return use

    def test_a_hard_block_ends_the_campaign_as_blocked(self, node):
        out, seen = node(make("Pistols for sale", **STRONG))
        assert out["rejected"] is True and seen["status"] == "blocked" and seen["saved"] == ["KILL"]
        from src.graph.nodes.decision import route_after_decision

        assert route_after_decision(out) == "end"

    def test_test_small_caps_the_campaign_and_goes_to_gate_1(self, node):
        out, seen = node(make("Merch", trend=(85, 70, True), news=3000, intent=(0, 0, 14)))
        assert out["decision"]["decision"] == "TEST_SMALL" and "rejected" not in out
        assert seen["updates"]["max_rounds"] == 2 and seen["status"] is None

    def test_a_soft_kill_still_goes_to_a_human_at_gate_1(self, node):
        out, seen = node(make("Fax repairs", trend=(2, 3, False), news=0, intent=(0, 0, 8), reach=(1, 3)))
        assert out["decision"]["decision"] == "KILL" and not out.get("rejected") and seen["status"] is None

    def test_an_engine_failure_carries_on_to_gate_1(self, monkeypatch, node):
        from src.graph.nodes import decision as node_mod

        def boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(node_mod, "inputs_from", boom)
        assert node_mod.decision_node({"campaign_id": "c1", "idea": "x"}) == {"decision": None}


class TestReevaluation:
    def test_a_wait_is_decided_again_once_interest_reaches_its_trigger(self, monkeypatch):
        waiting = make("Padel grips", trend=(25, 8, True), news=10, intent=(4, 2, 6), reach=(2, 3))
        first = evaluate(make("Padel grips", trend=(25, 8, True), news=10, intent=(0, 1, 13), reach=(2, 3)), now=NOW)
        row = {"decision": "WAIT", "reevaluate": first.reevaluate, "inputs": waiting.snapshot(), "org_id": "o1", "user_id": "u1"}
        saved = []

        class Q:
            def __getattr__(self, name):
                return lambda *a, **k: self

            def execute(self):
                return type("R", (), {"data": [row]})()

        monkeypatch.setattr("src.db.supabase_client.get_client", lambda: type("C", (), {"table": lambda s, n: Q()})())
        monkeypatch.setattr(dmod, "save", lambda d, i, **k: saved.append((d.decision, k["trigger"])))
        campaign = {"id": "c1", "status": "awaiting_gate_1"}
        assert dmod.reevaluate_waiting(campaign, {"latest_interest": 20, "mean_interest": 8}, None, now=NOW) is None  # below threshold
        again = dmod.reevaluate_waiting(campaign, {"latest_interest": 60, "mean_interest": 30, "trending_up": True}, None, now=NOW)
        assert again is not None and again.decision != "WAIT" and saved == [(again.decision, "reevaluation")]
        assert dmod.reevaluate_waiting({**campaign, "status": "awaiting_gate_2"}, {"latest_interest": 60}, None) is None


def test_the_campaign_outcome_is_written_back(monkeypatch):
    calls = []

    class Q:
        def __init__(self):
            self.patch = None

        def select(self, *a):
            return self

        def eq(self, *a):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, *a):
            return self

        def update(self, patch):
            calls.append(patch)
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "d1"}]})()

    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: type("C", (), {"table": lambda s, n: Q()})())
    dmod.record_outcome("c1", {"total_rounds": 2, "winning_round": {"reward": 0.3}, "reward_trend": [{"reward": 0.1}, {"reward": 0.3}]})
    assert calls[0]["outcome"]["rounds"] == 2 and calls[0]["outcome"]["mean_reward"] == 0.2


def test_feasibility_stamps_signals_and_keeps_post_texts_out_of_the_prompt(monkeypatch, fake_llm):
    from src.capabilities import feasibility as fmod

    llm = fake_llm('{"keywords_en": "water bottles", "keywords_localized": "water bottles"}', "Looks promising.")
    monkeypatch.setattr(fmod, "get_llm", lambda *a: llm)
    monkeypatch.setattr(fmod, "get_trend_interest", lambda k, hl=None: {"keyword": k, "mean_interest": 40, "latest_interest": 50, "trending_up": True})
    monkeypatch.setattr(fmod, "get_news_volume", lambda k, language=None: {"keyword": k, "total_results": 20, "headlines": ["h1"]})
    monkeypatch.setattr(fmod, "search_bluesky", lambda k: {"keyword": k, "result_count": 2, "avg_score": 3.0, "avg_comments": 1.0,
                                                          "texts": ["SECRET POST TEXT where to buy"]})
    monkeypatch.delenv("MASTODON_ACCESS_TOKEN", raising=False)
    result = fmod.score_feasibility("Water bottles")
    assert all(v.get("fetched_at") for v in result.signals.values())
    assert result.signals["bluesky"]["texts"] == ["SECRET POST TEXT where to buy"]
    assert "SECRET POST TEXT" not in llm.prompts[-1]


def test_no_trends_data_for_a_phrase_is_missing_evidence_not_zero_demand():
    inputs = make("Order-ahead coffee for metro commuters", news=9, intent=(4, 2, 6))
    inputs.trend = {"keyword": "order ahead coffee", "mean_interest": 0, "latest_interest": 0, "trending_up": False,
                    "no_data": True, "fetched_at": FRESH}
    d = evaluate(inputs, now=NOW)
    demand = next(f for f in d.factors if f.key == "demand")
    assert demand.score is None and "too little data" in demand.value
    assert "MISSING_DEMAND_DATA" in d.reason_codes and "WEAK_DEMAND" not in d.reason_codes
