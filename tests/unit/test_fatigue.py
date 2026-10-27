"""Creative fatigue (src/capabilities/fatigue.py): the documented rule (enough
data, sustained, significant, specific to the creative), duplicates kept apart
from fatigue, the refresh strategy and its measured outcome, and the refresh
reaching the next round's creative. Database rules are in
tests/integration/test_db_fatigue.py."""
import pytest

from src.capabilities import fatigue as fx
from src.capabilities.fatigue import (
    analyze_segment, duplicates, evaluate_refresh, features, pick_arm, refresh_constraints, refresh_directive, similarity,
    suggested_strategy,
)
from src.eval.fatigue_benchmark import run as benchmark


def periods(rates, people=1000, **extra):
    return [{"round": i + 1, "exposures": people, "successes": round(r * people), "stale": False, **extra} for i, r in enumerate(rates)]


WORN = (0.06, 0.06, 0.045, 0.036, 0.03)


class TestRule:
    def test_a_worn_out_concept_is_confirmed_and_near_identical_ones_retired(self):
        v = analyze_segment(periods(WORN), similarity_to_fresh=0.9)
        assert v["status"] == "FATIGUE_CONFIRMED" and v["recommendation"] == "RETIRE"
        assert v["baseline"]["rounds"] == [1, 2] and v["recent"]["rounds"] == [4, 5]
        assert v["relative_drop"] == pytest.approx(0.45, abs=0.01) and v["interval"][1] < 0 and v["sustained"]
        assert analyze_segment(periods(WORN), similarity_to_fresh=0.78)["recommendation"] == "TEST_REFRESH"

    def test_no_denominator_is_never_fatigue(self):
        social = [{"round": i, "exposures": None, "successes": None, "stale": False} for i in range(1, 6)]
        v = analyze_segment(social, similarity_to_fresh=0.95)
        assert (v["status"], v["reason"], v["recommendation"]) == ("NOT_MEASURABLE", "NO_EXPOSURE_DATA", "KEEP")

    def test_too_little_or_stale_data_is_insufficient(self):
        assert analyze_segment(periods(WORN, people=60), similarity_to_fresh=0.9)["status"] == "INSUFFICIENT_DATA"
        assert analyze_segment(periods(WORN[:2]), similarity_to_fresh=0.9)["reason"] == "TOO_FEW_ROUNDS_OR_PEOPLE"
        stale = periods(WORN)
        for p in stale[2:]:
            p["stale"] = True
        assert analyze_segment(stale, similarity_to_fresh=0.9)["reason"] == "STALE_OR_MISSING_METRICS"

    def test_one_bad_round_or_a_small_dip_is_not_fatigue(self):
        assert analyze_segment(periods((0.05, 0.05, 0.05, 0.03, 0.05)), similarity_to_fresh=0.9)["status"] == "NO_FATIGUE"
        v = analyze_segment(periods((0.05, 0.05, 0.05, 0.046, 0.046)), similarity_to_fresh=0.9)
        assert v["status"] == "NO_FATIGUE" and v["reason"] in ("DROP_TOO_SMALL", "NO_SUSTAINED_DROP")

    def test_a_large_drop_that_isnt_clear_yet_is_only_suspected(self):
        v = analyze_segment(periods((0.05, 0.05, 0.05, 0.035, 0.035), people=500), similarity_to_fresh=0.9)
        assert v["status"] == "FATIGUE_SUSPECTED" and v["recommendation"] == "TEST_REFRESH" and v["interval"][1] >= 0

    def test_a_drop_the_creative_doesnt_explain(self):
        market = analyze_segment(periods(WORN), similarity_to_fresh=0.9, comparators=[0.4])
        assert (market["status"], market["reason"]) == ("NOT_ATTRIBUTABLE", "MARKET_OR_AUDIENCE_DROP")
        assert analyze_segment(periods(WORN), similarity_to_fresh=0.9, comparators=[0.05])["status"] == "FATIGUE_CONFIRMED"
        differ = analyze_segment(periods(WORN), similarity_to_fresh=0.4)
        assert (differ["status"], differ["recommendation"]) == ("NOT_ATTRIBUTABLE", "KEEP") and differ["reason"] == "CREATIVES_DIFFER"


IT = {"round_number": 1, "copy_text": "Get 20% off your first order. Coffee ready when you arrive.", "cta": "Order now",
      "template": "centered_hero", "image_style": "minimalist", "copy_tone": "direct_factual", "arm_index": 0,
      "copy_text_b": "Skip the queue every morning.", "image_style_b": "humor_meme", "copy_tone_b": "humorous", "arm_index_b": 9}


class TestSimilarity:
    def test_features_of_each_variant(self):
        a, b = features(IT), features(IT, "b")
        assert a["hook"] == "Get 20% off your first order." and a["offer"] == "20% off" and a["template"] == "centered_hero"
        assert b["copy"] == "Skip the queue every morning." and b["image_style"] == "humor_meme" and b["template"] is None

    def test_weighted_similarity_ignores_an_offer_neither_has(self):
        a = features({**IT, "copy_text": "Coffee ready when you arrive."})
        s = similarity(a, a, 1.0)
        assert s["total"] == 1.0 and "offer" not in s
        other = features({**IT, "copy_text": "Brand new beans.", "template": "dark_glow", "image_style": "lifestyle_aspirational", "cta": "Shop"})
        assert similarity(a, other, 0.2)["total"] < 0.3

    def test_duplicates_are_reported_apart_from_fatigue(self):
        same = [features({**IT, "round_number": r}) for r in (1, 2, 3)]
        dup = duplicates(same, [[1.0] * 3] * 3)
        assert [(d["round"], d["of_round"]) for d in dup] == [(2, 1), (3, 1)]
        fresh = [features({**IT, "round_number": 1}), features({**IT, "round_number": 2, "copy_text": "Different words.",
                                                               "template": "dark_glow", "image_style": "humor_meme", "cta": "Try"})]
        assert duplicates(fresh, [[1.0, 0.1], [0.1, 1.0]]) == []


class TestRefresh:
    def test_change_what_repeats_most_unless_experience_says_otherwise(self):
        sim = {"copy": 0.5, "visual": 1.0, "hook": 0.9, "cta": 1.0, "total": 0.8}
        assert suggested_strategy(sim)[0] == "NEW_VISUAL"
        learned = {"NEW_HOOK": (4, 5), "NEW_VISUAL": (0, 3)}
        pick, record = suggested_strategy(sim, learned)
        assert pick == "NEW_HOOK" and record["NEW_HOOK"]["posterior_mean"] == pytest.approx(5 / 7, abs=1e-3)
        assert suggested_strategy(sim, {"NEW_HOOK": (1, 1)})[0] == "NEW_VISUAL"  # one try proves nothing

    def test_directives_never_invite_new_claims(self):
        c = refresh_constraints([features(IT)], [features({**IT, "round_number": 2})])
        hook = refresh_directive("NEW_HOOK", c)
        assert "“Get 20% off your first order.”" in hook and "keep the facts the same" in hook
        assert "Do not invent offers, prices or deadlines." in refresh_directive("NEW_OFFER_FRAMING", c)

    def test_a_visual_or_angle_refresh_changes_the_arm(self):
        c = {"avoid_styles": ["minimalist"], "avoid_tones": ["direct_factual"]}
        arms = [(0, "minimalist", "direct_factual"), (3, "minimalist", "humorous"), (9, "humor_meme", "direct_factual")]
        assert pick_arm("NEW_VISUAL", c, arms) == (9, "humor_meme", "direct_factual")
        assert pick_arm("NEW_ANGLE", c, arms) == (3, "minimalist", "humorous")
        assert pick_arm("NEW_HOOK", c, arms) is None

    def test_the_outcome_needs_an_interval_clear_of_zero(self):
        assert evaluate_refresh((60, 2000), (90, 1000), 0.06)["outcome"] == "IMPROVED"
        assert evaluate_refresh((60, 2000), (90, 1000), 0.06)["recovered_to_fresh"] is True
        assert evaluate_refresh((90, 2000), (20, 1000), 0.06)["outcome"] == "WORSE"
        assert evaluate_refresh((600, 20000), (600, 20000), 0.06)["outcome"] == "NO_CHANGE"
        assert evaluate_refresh((30, 1000), (40, 1000), 0.06)["outcome"] == "INCONCLUSIVE"
        assert evaluate_refresh((60, 2000), (5, 50), 0.06) == {"outcome": "INCONCLUSIVE", "reason": "TOO_FEW_PEOPLE", "design": "sequential"}


def test_the_next_round_gets_the_refresh(monkeypatch):
    from src.graph.nodes import creative as node

    seen = {}
    monkeypatch.setattr(node, "generate_creative", lambda *a, **k: seen.update(k) or "creative")
    monkeypatch.setattr(node, "brand_kit_for_campaign", lambda cid: None)
    monkeypatch.setattr(node, "playbook_section_for_campaign", lambda cid: "")
    monkeypatch.setattr(node, "product_for_campaign", lambda cid: type("P", (), {"cutout": None, "tagline": "", "template": ""})())
    monkeypatch.setattr(fx, "apply_pending_refresh", lambda cid, rnd, candidates_fn=None: ("Use a new hook.", (9, "humor_meme", "humorous")))
    persona = type("P", (), {"age_bracket": "25-34", "income_tier": "middle"})()
    node.creative_node({"idea": "i", "primary_persona": persona, "domain_category": "other", "campaign_id": "c1", "round_id": 3,
                        "revision_directive": "Shorter copy."})
    assert seen["revision_directive"] == "Shorter copy.\nUse a new hook." and seen["arm"] == (9, "humor_meme", "humorous")
    # Round 1 has nothing to refresh.
    node.creative_node({"idea": "i", "primary_persona": persona, "domain_category": "other", "campaign_id": "c1", "round_id": 1})
    assert seen["revision_directive"] is None and seen["arm"] is None


def test_email_periods_use_recipients_when_people_arent_tracked(monkeypatch):
    monkeypatch.setattr("src.capabilities.impact.experiment_for", lambda cid: None)
    its = [{"round_number": 1, "copy_text": "x"}, {"round_number": 2, "copy_text": "y"}, {"round_number": 3, "copy_text": "z"}]
    metrics = [{"round_number": 1, "channel": "email", "raw_metrics": {"clicks": 30, "recipients": 500}},
               {"round_number": 2, "channel": "email", "raw_metrics": {"clicks": 900, "recipients": 500}}]  # repeat clicks: capped
    p = fx.email_periods("c1", its, metrics, "a")
    assert p[0] == {"round": 1, "exposures": 500, "successes": 30, "unique": False, "stale": False}
    assert p[1]["successes"] == 500 and p[2]["stale"] is True  # round 3's metrics never arrived


def test_the_benchmark_meets_its_bar():
    rows = {r["key"]: r for r in benchmark(draws=200)}
    no_fatigue = [r for r in rows.values() if not r["truth"]]
    assert sum(r["engine_alarm"] for r in no_fatigue) / len(no_fatigue) <= 0.15
    assert sum(r["engine_alarm"] for r in no_fatigue) < sum(r["naive_alarm"] for r in no_fatigue)
    assert rows["worn_out"]["engine_alarm"] >= 0.7
    assert rows["social"]["top_status"] == "NOT_MEASURABLE" and rows["small_list"]["top_status"] == "INSUFFICIENT_DATA"
    assert rows["creatives_differ"]["engine_alarm"] == 0
