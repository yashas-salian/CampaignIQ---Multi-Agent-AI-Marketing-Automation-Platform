"""Proof-of-impact engine (src/capabilities/impact.py): stable assignment, the
statistics, the pre-registered verdicts, the per-recipient send and the
bandit feed. The database side (pre-registration lock, matching conversions,
RLS) is in tests/integration/test_db_experiments.py."""
from datetime import datetime, timedelta, timezone

import pytest

from src.capabilities import impact
from src.capabilities.impact import (
    analyze, analyze_counts, assign_arm, bandit_rewards, impact_api_view, newcombe_diff, sample_size_per_arm,
    srm_p_value, unit_hash, wilson,
)
from src.eval.impact_benchmark import run as benchmark

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
EXP = {
    "id": "e1", "campaign_id": "c1", "design": "holdout", "primary_metric": "qualified_signup_rate", "control_share": 0.2,
    "attribution_window_days": 7, "duration_days": 14, "min_units_per_arm": 100, "min_effect": 0.01,
    "started_at": START.isoformat(), "ends_at": (START + timedelta(days=14)).isoformat(),
    "analysis_at": (START + timedelta(days=21)).isoformat(),
}
FINAL = START + timedelta(days=22)


def rows(groups: dict[str, tuple[int, int]], *, when=START + timedelta(days=2), kind="conversion", qualified=True):
    """{arm: (units, successes)} -> assignments, events."""
    assignments, events = [], []
    for arm, (n, k) in groups.items():
        for i in range(n):
            uid = f"{arm}{i}"
            assignments.append({"id": uid, "arm": arm})
            if i < k:
                events.append({"assignment_id": uid, "arm": arm, "kind": kind, "qualified": qualified, "value": None,
                               "currency": None, "round_number": 1, "occurred_at": when.isoformat()})
    return assignments, events


class TestAssignment:
    def test_the_same_unit_always_gets_the_same_arm(self):
        h = unit_hash("e1", "  Ava@Example.com ")
        assert h == unit_hash("e1", "ava@example.com")  # normalised
        assert unit_hash("e2", "ava@example.com") != h  # independent between experiments
        assert {assign_arm("e1", h, "holdout", 0.2) for _ in range(5)} == {assign_arm("e1", h, "holdout", 0.2)}

    def test_the_split_matches_the_declared_shares(self):
        hashes = [unit_hash("e1", f"user{i}@x.io") for i in range(10000)]
        holdout = [assign_arm("e1", h, "holdout", 0.2) for h in hashes]
        assert 0.185 < holdout.count("control") / 10000 < 0.215
        three = [assign_arm("e1", h, "holdout_ab", 0.2) for h in hashes]
        assert abs(three.count("treatment") - three.count("treatment_b")) < 300
        assert set(assign_arm("e1", h, "ab", 0) for h in hashes) == {"treatment", "treatment_b"}
        # Control units stay control when the A/B split is added: the holdout is decided first.
        assert [a == "control" for a in holdout] == [a == "control" for a in three]


class TestStatistics:
    def test_newcombe_matches_the_published_example(self):
        # Newcombe (1998), Statistics in Medicine 17:873, example (a): 56/70 vs 48/80.
        d, lo, hi = newcombe_diff(56, 70, 48, 80)
        assert round(d, 4) == 0.2 and round(lo, 4) == 0.0524 and round(hi, 4) == 0.3339

    def test_zero_conversions_and_small_samples_stay_sensible(self):
        assert wilson(0, 10) == (0.0, pytest.approx(0.2775, abs=1e-4))
        d, lo, hi = newcombe_diff(0, 10, 0, 10)
        assert d == 0 and lo < 0 < hi and -1 <= lo and hi <= 1
        d, lo, hi = newcombe_diff(5, 5, 0, 5)  # all vs none
        assert d == 1 and 0 < lo < 1 and hi == 1
        assert newcombe_diff(1, 0, 0, 5) is None

    def test_unequal_groups(self):
        d, lo, hi = newcombe_diff(400, 9500, 20, 500)
        assert d == pytest.approx(400 / 9500 - 20 / 500) and lo < d < hi
        # The interval is set by the small group: it's much wider than with balanced groups of the same total.
        _, blo, bhi = newcombe_diff(210, 5000, 210, 5000)
        assert (hi - lo) > (bhi - blo)

    def test_sample_ratio_mismatch(self):
        assert srm_p_value({"control": 2000, "treatment": 8000}, {"control": 0.2, "treatment": 0.8}) == 1.0
        assert srm_p_value({"control": 1500, "treatment": 8500}, {"control": 0.2, "treatment": 0.8}) < 1e-6
        three = {"control": 0.2, "treatment": 0.4, "treatment_b": 0.4}
        assert srm_p_value({"control": 200, "treatment": 410, "treatment_b": 390}, three) > 0.5

    def test_sample_size_for_planning(self):
        assert 3700 < sample_size_per_arm(0.02, 0.01) < 3900  # 2% -> 3%, 80% power
        assert sample_size_per_arm(0.99, 0.02) is None


class TestVerdicts:
    def test_no_verdict_before_the_predeclared_end(self):
        a, e = rows({"control": (200, 2), "treatment": (800, 60)})
        r = analyze(EXP, a, e, now=START + timedelta(days=5))
        assert r["status"] == "COLLECTING" and r["interim"] and not r["final"]
        assert r["estimate"]["absolute_lift"] > 0  # interim numbers are shown, the verdict isn't
        assert r["recommended_action"] is None

    def test_positive_impact_with_its_interval(self):
        a, e = rows({"control": (2000, 60), "treatment": (8000, 400)})
        r = analyze(EXP, a, e, now=FINAL)
        est = r["estimate"]
        assert r["status"] == "POSITIVE_IMPACT" and r["final"]
        assert est["control_rate"] == 0.03 and est["treatment_rate"] == 0.05 and est["absolute_lift"] == 0.02
        assert est["interval"][0] > 0 and est["prob_treatment_better"] > 0.99
        assert est["relative_lift"] == pytest.approx(0.67, abs=0.06) and est["relative_interval"][0] > 0
        assert est["incremental_successes"] == 160.0 and est["causal"]
        assert r["practically_significant"]

    def test_inconclusive_reasons(self):
        a, e = rows({"control": (2000, 0), "treatment": (8000, 0)})
        assert analyze(EXP, a, e, now=FINAL)["reason"] == "NO_OUTCOME_DATA"
        a, e = rows({"control": (40, 1), "treatment": (160, 9)})
        assert analyze(EXP, a, e, now=FINAL)["reason"] == "INSUFFICIENT_DATA"
        a, e = rows({"control": (1500, 45), "treatment": (8500, 255)})
        r = analyze(EXP, a, e, now=FINAL)
        assert r["reason"] == "SAMPLE_RATIO_MISMATCH" and r["quality"]["sample_ratio_mismatch"]
        a, e = rows({"control": (300, 9), "treatment": (1200, 40)})
        assert analyze(EXP, a, e, now=FINAL)["reason"] == "INTERVAL_TOO_WIDE"

    def test_no_meaningful_impact_needs_a_tight_interval_around_zero(self):
        r = analyze_counts(20000, 600, 20000, 610, min_effect=0.01)
        assert r["status"] == "NO_MEANINGFUL_IMPACT"
        assert analyze_counts(20000, 600, 20000, 610, min_effect=0.001)["status"] == "INCONCLUSIVE"

    def test_relative_lift_only_with_a_supported_baseline(self):
        r = analyze_counts(500, 4, 2000, 60, min_effect=0.01)
        assert r["estimate"]["relative_lift"] is None and r["estimate"]["relative_note"] == "BASELINE_TOO_THIN"
        assert r["estimate"]["absolute_lift"] is not None

    def test_only_outcomes_in_the_window_count_and_strangers_are_kept_apart(self):
        a, e = rows({"control": (200, 0), "treatment": (800, 0)})
        late = START + timedelta(days=30)
        early = START - timedelta(days=1)
        e += [
            {"assignment_id": "treatment0", "arm": "treatment", "kind": "conversion", "qualified": True, "value": None,
             "currency": None, "round_number": None, "occurred_at": late.isoformat()},
            {"assignment_id": "treatment1", "arm": "treatment", "kind": "conversion", "qualified": True, "value": None,
             "currency": None, "round_number": None, "occurred_at": early.isoformat()},
            {"assignment_id": None, "arm": None, "kind": "conversion", "qualified": True, "value": None,
             "currency": None, "round_number": None, "occurred_at": (START + timedelta(days=2)).isoformat()},
        ]
        r = analyze(EXP, a, e, now=FINAL)
        assert r["arms"]["treatment"]["successes"] == 0
        assert r["quality"]["conversions_received"] == 3 and r["quality"]["unmatched_conversions"] == 1
        assert "UNMATCHED_CONVERSIONS_EXCLUDED" in r["assumptions"]

    def test_qualified_signups_ignore_unqualified_conversions(self):
        a, e = rows({"control": (200, 10), "treatment": (800, 80)}, qualified=False)
        r = analyze(EXP, a, e, now=FINAL)
        assert r["arms"]["treatment"]["converters"] == 80 and r["arms"]["treatment"]["successes"] == 0
        assert analyze({**EXP, "primary_metric": "conversion_rate"}, a, e, now=FINAL)["arms"]["treatment"]["successes"] == 80

    def test_revenue_keeps_the_causal_estimate_and_attribution_apart(self):
        a, e = rows({"control": (300, 0), "treatment": (1200, 0)})
        t = START + timedelta(days=2)
        for i in range(30):  # control converts too: it just never clicked anything
            e.append({"assignment_id": f"control{i}", "arm": "control", "kind": "conversion", "qualified": True, "value": 10,
                      "currency": "USD", "round_number": None, "occurred_at": t.isoformat()})
        for i in range(240):
            e.append({"assignment_id": f"treatment{i}", "arm": "treatment", "kind": "click", "qualified": False, "value": None,
                      "currency": None, "round_number": 1, "occurred_at": (t - timedelta(hours=1)).isoformat()})
            e.append({"assignment_id": f"treatment{i}", "arm": "treatment", "kind": "conversion", "qualified": True, "value": 10,
                      "currency": "USD", "round_number": None, "occurred_at": t.isoformat()})
        r = analyze(EXP, a, e, now=FINAL)
        rev = r["revenue"]
        # Last-click attribution credits every clicker's purchase; the randomized
        # estimate subtracts what the control group bought anyway.
        assert rev["attributed_revenue"] == 2400.0
        assert rev["incremental_revenue"] == pytest.approx((240 * 10 / 1200 - 30 * 10 / 300) * 1200)
        assert rev["incremental_revenue"] < rev["attributed_revenue"]
        assert "not causal" in rev["attribution_model"]

    def test_stale_and_silent_outcome_sources_are_flagged(self):
        a, e = rows({"control": (200, 0), "treatment": (800, 0)})
        r = analyze(EXP, a, e, now=START + timedelta(days=5))
        assert r["quality"]["no_conversions_yet"]
        a, e = rows({"control": (200, 2), "treatment": (800, 9)}, when=START + timedelta(days=1))
        assert analyze(EXP, a, e, now=START + timedelta(days=6))["quality"]["stale_outcomes"]

    def test_ab_compares_b_with_a_and_may_use_clicks(self):
        exp = {**EXP, "design": "ab", "control_share": 0, "primary_metric": "click_through_rate"}
        a, e = rows({"treatment": (1000, 30), "treatment_b": (1000, 70)}, kind="click")
        r = analyze(exp, a, e, now=FINAL)
        assert r["estimate"]["treatment_arms"] == ["treatment_b"] and r["estimate"]["control_arms"] == ["treatment"]
        assert r["status"] == "POSITIVE_IMPACT" and "CONTROL_SEES_OTHER_CHANNELS" not in r["assumptions"]

    def test_holdout_ab_pools_both_variants_against_control_and_compares_them_too(self):
        exp = {**EXP, "design": "holdout_ab"}
        a, e = rows({"control": (2000, 60), "treatment": (4000, 200), "treatment_b": (4000, 200)})
        r = analyze(exp, a, e, now=FINAL)
        assert r["estimate"]["treatment_units"] == 8000 and r["secondary"]["absolute_lift"] == 0

    def test_the_api_view_matches_the_spec(self):
        assert impact_api_view(None) == {
            "status": "INCONCLUSIVE", "primaryMetric": None, "controlRate": None, "treatmentRate": None,
            "absoluteLift": None, "confidenceOrCredibleInterval": None, "reason": "NOT_ANALYZED_YET",
        }
        view = impact_api_view(analyze_counts(2000, 60, 8000, 400))
        assert view["status"] == "POSITIVE_IMPACT" and view["confidenceOrCredibleInterval"][0] > 0


class TestBandit:
    def test_rewards_credit_the_latest_email_before_the_success(self):
        a = [{"id": "u1", "arm": "treatment"}, {"id": "u2", "arm": "treatment"}, {"id": "c1", "arm": "control"}]

        def ev(uid, kind, day, rnd=None, qualified=True):
            return {"assignment_id": uid, "arm": None, "kind": kind, "qualified": qualified, "value": None, "currency": None,
                    "round_number": rnd, "occurred_at": (START + timedelta(days=day)).isoformat()}

        events = [ev("u1", "exposure", 0, 1), ev("u2", "exposure", 0, 1), ev("u1", "exposure", 3, 2), ev("u2", "exposure", 3, 2),
                  ev("u1", "conversion", 4), ev("u2", "conversion", 1), ev("c1", "conversion", 1)]
        result = analyze(EXP, a, events, now=FINAL)
        got = {(r["round"], r["arm"]): (r["successes"], r["units"]) for r in bandit_rewards(EXP, a, events, result)}
        assert got == {(1, "treatment"): (1, 2), (2, "treatment"): (1, 2)}  # the control's conversion teaches nothing

    def test_a_broken_experiment_never_feeds_the_bandit(self, monkeypatch):
        result = {"reason": "SAMPLE_RATIO_MISMATCH"}
        assert impact.feed_bandit(EXP, {}, [], [], result) == {"fed": False, "reason": "SAMPLE_RATIO_MISMATCH"}
        assert impact.feed_bandit({**EXP, "bandit_fed_at": "x"}, {}, [], [], {"reason": "INTERVAL_ABOVE_ZERO"})["reason"] == "ALREADY_FED"


class TestSending:
    def test_each_recipient_gets_their_own_link_and_key(self, monkeypatch):
        from src.capabilities import distribution

        sent, exposures = [], []
        monkeypatch.setenv("TRACK_CLICK_BASE_URL", "https://x.supabase.co/functions/v1/track-click")
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, image_bytes=None, idempotency_key=None:
                            sent.append((to, html, idempotency_key)) or f"id-{len(sent)}")
        monkeypatch.setattr(impact, "record_exposures", lambda exp, rnd, hashes: exposures.append((exp, rnd, hashes)))
        monkeypatch.setattr(impact, "SEND_PACING_SECONDS", 0)
        payload = {"experiment_id": "e1", "subject": "Hi", "cta_url": "https://brew.example/?ref=ad",
                   "html": f'<p>Coffee</p><p><a href="{distribution.LINK_SLOT}">Learn more</a></p>',
                   "per_recipient": [{"to": "a@x.io", "token": "a" * 32, "unit_hash": "h" * 64},
                                     {"to": "b@x.io", "token": "b" * 32, "unit_hash": "k" * 64}]}
        ref = distribution._send_each("c1", 2, "email", payload, None)
        assert ref == "2 emails (id-1)"
        assert [s[0] for s in sent] == [["a@x.io"], ["b@x.io"]]  # one address per email
        assert "t=" + "a" * 32 in sent[0][1] and "b" * 32 not in sent[0][1]
        assert sent[0][2] == "c1:2:email:" + "h" * 32 and sent[0][2] != sent[1][2]
        assert exposures == [("e1", 2, ["h" * 64, "k" * 64])]

    def test_a_partial_failure_still_records_who_was_emailed(self, monkeypatch):
        from src.capabilities import distribution

        exposures = []

        def flaky(to, *a, **k):
            if to == ["b@x.io"]:
                raise RuntimeError("rate limited")
            return "id"

        monkeypatch.setattr(distribution, "send_email", flaky)
        monkeypatch.setattr(impact, "record_exposures", lambda exp, rnd, hashes: exposures.append(hashes))
        monkeypatch.setattr(impact, "SEND_PACING_SECONDS", 0)
        payload = {"experiment_id": "e1", "subject": "Hi", "cta_url": None, "html": "<p>x</p>",
                   "per_recipient": [{"to": "a@x.io", "token": "a" * 32, "unit_hash": "h1"},
                                     {"to": "b@x.io", "token": "b" * 32, "unit_hash": "h2"}]}
        with pytest.raises(RuntimeError):
            distribution._send_each("c1", 1, "email", payload, None)
        assert exposures == [["h1"]]

    def test_without_click_tracking_the_token_still_reaches_the_site(self, monkeypatch):
        from src.capabilities.distribution import personal_link

        monkeypatch.delenv("TRACK_CLICK_BASE_URL", raising=False)
        assert personal_link("https://brew.example/?ref=ad&ciq_t=old", campaign_id="c", round_id=1, channel="email",
                             token="f" * 32) == "https://brew.example/?ref=ad&ciq_t=" + "f" * 32

    def test_the_control_group_is_never_emailed(self, monkeypatch):
        from src.graph.nodes import distribution_email as node

        units = {
            "a@x.io": {"arm": "treatment", "token": "1" * 32, "unit_hash": "ha"},
            "b@x.io": {"arm": "control", "token": "2" * 32, "unit_hash": "hb"},
            "c@x.io": {"arm": "treatment_b", "token": "3" * 32, "unit_hash": "hc"},
        }
        calls = []
        monkeypatch.setattr(node.impact, "experiment_for", lambda cid: {"id": "e1", "status": "declared"})
        monkeypatch.setattr(node.impact, "start", lambda exp, addresses: units)
        monkeypatch.setattr(node, "send_experiment_email", lambda cid, rnd, recipients, *a, **k: calls.append([r["to"] for r in recipients]) or "ok")
        monkeypatch.setattr(node, "upsert_iteration", lambda *a, **k: None)
        monkeypatch.setattr(node, "brand_kit_for_campaign", lambda cid: None)
        creative = type("C", (), {"copy_text": "Fresh coffee, ready when you arrive.", "image_bytes": b"", "headline": "Coffee"})()
        state = {"campaign_id": "c1", "round_id": 1, "user_id": "u1", "idea": "Coffee", "email_to": list(units),
                 "creative": creative, "creative_b": None, "domain_category": "other", "cta_url": None}
        node.distribution_email_node(state)
        assert calls == [["a@x.io", "c@x.io"]]  # A/B off: both treatment groups get the one creative; never b@x.io


def test_the_early_ab_stop_waits_for_a_running_experiment(monkeypatch):
    from src.graph.nodes import metrics_collector as node

    monkeypatch.setattr("src.capabilities.impact.experiment_for", lambda cid: {"status": "running"})
    assert node._fixed_horizon("c1") is True
    monkeypatch.setattr("src.capabilities.impact.experiment_for", lambda cid: None)
    assert node._fixed_horizon("c1") is False


def test_the_benchmark_meets_its_bar():
    rows = {r["key"]: r for r in benchmark(draws=100)}
    nulls = [r for r in rows.values() if r["truth"] == "NONE"]
    assert sum(r["engine_false_claims"] for r in nulls) / len(nulls) <= 0.08
    assert rows["positive"]["engine_right"] >= 0.9 and rows["negative"]["engine_right"] >= 0.9
    assert rows["broken_split"]["top_reason"] == "SAMPLE_RATIO_MISMATCH" and rows["broken_split"]["engine_right"] == 1
    assert rows["zero_conversions"]["top_reason"] == "NO_OUTCOME_DATA"
    assert rows["seasonal_rise"]["before_after_false_claims"] > 0.9  # the shortcut the control group protects against
