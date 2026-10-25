"""Campaign crash test (src/capabilities/crash_test.py): rule checks, the
simulated scenarios (fake LLM), revision and comparison, the graph step, and
applying a revision at Gate 2. No network."""
import json

import pytest

from src.capabilities import crash_test as ct
from src.capabilities.crash_test import AdText, compare, locate, risk_of, rule_checks, run_crash_test
from src.eval.crashtest_benchmark import run as benchmark

IDEA = "Order-ahead coffee app for metro commuters. First order free."
COFFEE = AdText(
    body="Rahul says the moment he steps off the metro, his coffee is waiting – no line. Grab your first order free now, "
         "enjoy it before the early‑bird spots run out. #Nothinghappened",
    headline="Your coffee ready on arrival", cta="Order Now", visual="a commuter holding a coffee",
)
CLEAN = AdText(body="Step off the metro and your coffee is already waiting. First order free.",
               headline="Coffee ready when you are", cta="Order now")


def types(findings, at_least="medium"):
    return {f.type for f in findings if ct._rank(f.severity) >= ct._rank(at_least)}


class TestRuleChecks:
    def test_the_real_smoke_test_ad_is_caught(self):
        found = rule_checks(COFFEE, idea=IDEA)
        assert {"INVENTED_TESTIMONIAL", "FALSE_URGENCY"} <= types(found)
        testimonial = next(f for f in found if f.type == "INVENTED_TESTIMONIAL")
        assert testimonial.severity == "critical" and testimonial.quote == "Rahul says" and testimonial.field == "body"
        assert risk_of(found) == "critical"

    def test_a_clean_ad_has_nothing_serious(self):
        assert not types(rule_checks(CLEAN, idea=IDEA), "high")

    def test_the_brands_own_words_are_never_invented(self):
        ad = AdText(body="Limited time: 20% off your first month.")
        assert {"FALSE_URGENCY", "UNVERIFIED_NUMBER"} <= types(rule_checks(ad, idea="Meal kits"))
        stated = rule_checks(ad, idea="Meal kits, 20% off the first month", tagline="Limited time only")
        assert not {"FALSE_URGENCY", "UNVERIFIED_NUMBER"} & types(stated)

    @pytest.mark.parametrize("body, expected", [
        ("Are you struggling with debt? Our app helps.", "PERSONAL_ATTRIBUTE"),
        ("12,000 commuters already joined.", "FAKE_SOCIAL_PROOF"),
        ("Rated 4.9 out of 5 by riders.", "INVENTED_TESTIMONIAL"),
        ("Only 3 free coffees left for today.", "FALSE_URGENCY"),
        ("Call +91 98765 43210 to order.", "POLICY_VIOLATION"),
    ])
    def test_each_rule(self, body, expected):
        assert expected in types(rule_checks(AdText(body=body), idea=IDEA))

    def test_pronouns_are_not_testimonials(self):
        assert "INVENTED_TESTIMONIAL" not in types(rule_checks(AdText(body="She says mornings are calmer now."), idea=IDEA))

    def test_the_on_image_headline_is_checked_too(self):
        found = rule_checks(AdText(body="Skip the queue.", headline="Visit coffeehub.io now"), idea=IDEA)
        assert any(f.type == "POLICY_VIOLATION" and "headline" in f.problem for f in found)

    def test_a_broken_link_is_critical_and_an_unchecked_one_is_low(self):
        assert risk_of(rule_checks(CLEAN, idea=IDEA, destination={"status": "invalid", "detail": "404"})) == "critical"
        low = rule_checks(CLEAN, idea=IDEA, destination={"status": "unverified", "detail": "timeout"})
        assert [f.severity for f in low if f.type == "UNVERIFIED_DESTINATION"] == ["low"]

    def test_rule_checks_are_reproducible_and_the_benchmark_holds(self):
        assert [f.model_dump() for f in rule_checks(COFFEE, idea=IDEA)] == [f.model_dump() for f in rule_checks(COFFEE, idea=IDEA)]
        result = benchmark()
        assert result["detected"] == result["planted"] and result["false_alarms"] == 0
        assert result["detected"] > result["baseline_detected"] and result["reproducible"]


class TestLocate:
    def test_quotes_are_found_whatever_the_quote_marks_hyphens_or_case(self):
        assert locate(COFFEE, "before the early-bird spots run out") == ("before the early-bird spots run out", "body")
        assert locate(COFFEE, "“YOUR COFFEE READY”")[1] == "headline"
        assert locate(COFFEE, "not in the ad at all") == (None, None)
        assert locate(COFFEE, "ok") == (None, None)


def fake_llm(monkeypatch, *replies):
    from tests.conftest import FakeLLM

    llm = FakeLLM(*[json.dumps(r) for r in replies])
    monkeypatch.setattr("src.providers.registry.get_llm", lambda *a, **k: llm)
    return llm


SIM = {"scenarios": [
    {"id": "skeptic", "verdict": "fail", "findings": [
        {"type": "TRUST_GAP", "severity": "critical", "quote": "Rahul says", "problem": "Who is Rahul?", "fix": "Drop him."}]},
    {"id": "three_second_scroll", "verdict": "concern", "findings": [
        {"type": "AMBIGUOUS_MESSAGE", "severity": "medium", "quote": "", "problem": "Is it a café or an app?", "fix": "Say app."}]},
    {"id": "made_up_scenario", "findings": [{"type": "TRUST_GAP", "severity": "high", "problem": "x"}]},
    {"id": "sensitivity", "findings": [{"type": "NOT_A_TYPE", "severity": "high", "problem": "x"},
                                       {"type": "INSENSITIVE", "severity": "high", "quote": "words not in the ad", "problem": "y"}]},
]}
REVISED = {"copy": "Step off the metro and your coffee is waiting. First order free.", "headline": "Coffee ready on arrival",
           "cta": "Order now", "changes": ["Removed the invented customer quote", "Removed the made-up deadline"]}
SIM_AFTER = {"scenarios": [{"id": "three_second_scroll", "verdict": "concern", "findings": [
    {"type": "AMBIGUOUS_MESSAGE", "severity": "low", "quote": "", "problem": "Still unclear it's an app.", "fix": "Say app."}]}]}


class TestSimulation:
    def test_findings_are_validated_anchored_and_capped(self, monkeypatch):
        fake_llm(monkeypatch, SIM)
        found = ct.simulate(COFFEE, idea=IDEA)
        by_type = {f.type: f for f in found}
        assert set(by_type) == {"TRUST_GAP", "AMBIGUOUS_MESSAGE", "INSENSITIVE"}  # unknown scenario/type dropped
        assert by_type["TRUST_GAP"].severity == "high"  # simulated people can't make anything critical
        assert by_type["TRUST_GAP"].quote == "Rahul says" and by_type["TRUST_GAP"].scenario == "skeptic"
        assert by_type["AMBIGUOUS_MESSAGE"].quote is None  # about the ad as a whole
        assert by_type["INSENSITIVE"].quote is None  # its "quote" wasn't in the ad: not anchored to invented text

    def test_the_whole_run_revises_and_compares(self, monkeypatch):
        llm = fake_llm(monkeypatch, SIM, REVISED, SIM_AFTER)
        report = run_crash_test(COFFEE, idea=IDEA)
        assert report.risk == "critical" and report.simulation_only and report.status == "COMPLETED"
        assert report.revised.body.startswith("Step off the metro") and report.revision_notes
        assert report.revised_risk in ("low", "clear")
        resolved = set(report.comparison["resolved"])
        assert any("INVENTED_TESTIMONIAL" in k for k in resolved) and any("TRUST_GAP" in k for k in resolved)
        assert len(llm.prompts) == 3  # simulate, revise, re-simulate

    def test_a_low_risk_ad_is_not_revised(self, monkeypatch):
        llm = fake_llm(monkeypatch, {"scenarios": []})
        report = run_crash_test(CLEAN, idea=IDEA)
        assert report.risk in ("clear", "low") and report.revised is None and len(llm.prompts) == 1

    def test_a_failed_simulation_keeps_the_rule_checks(self, monkeypatch):
        def down(*a, **k):
            raise RuntimeError("every LLM provider failed")

        monkeypatch.setattr("src.providers.registry.get_llm", down)
        report = run_crash_test(COFFEE, idea=IDEA)
        assert report.status == "RULES_ONLY" and report.risk == "critical" and "couldn't run" in report.note

    def test_the_prompts_ask_for_quotes_and_forbid_invention(self, monkeypatch):
        llm = fake_llm(monkeypatch, SIM, REVISED, SIM_AFTER)
        run_crash_test(COFFEE, idea=IDEA)
        assert "competitor offer 20% off" in llm.prompts[0] and "copied character for character" in llm.prompts[0]
        assert "no customer names" in llm.prompts[1] and "Rahul says" in llm.prompts[1]


def test_compare_matches_rules_on_quotes_and_simulation_on_scenario():
    a = ct._finding("rule", "FALSE_URGENCY", "high", "p", "f", COFFEE, "run out")
    b = ct._finding("simulation", "TRUST_GAP", "high", "p", "f", COFFEE, "Rahul says", scenario="skeptic")
    revised_ad = AdText(body="Different words entirely.")
    c = ct._finding("simulation", "TRUST_GAP", "medium", "p", "f", revised_ad, None, scenario="skeptic")
    d = ct._finding("rule", "UNVERIFIED_NUMBER", "medium", "p", "f", revised_ad, None)
    result = compare([a, b], [c, d])
    assert result["resolved"] == [a.key] and result["remaining"] == [c.key] and result["new"] == [d.key]


class TestGraphStep:
    def test_the_node_crash_tests_the_round_and_never_fails_the_gate(self, monkeypatch):
        from src.graph.nodes import crash_test as node

        seen = {}
        monkeypatch.setattr(node, "run_for_round", lambda cid, rnd, **k: seen.update(cid=cid, rnd=rnd, ad=k["ad"]))
        creative = type("C", (), {"copy_text": "Hi", "headline": "H", "cta": "Go", "image_prompt": "p"})()
        assert node.crash_test_node({"campaign_id": "c1", "round_id": 2, "creative": creative, "idea": IDEA}) == {}
        assert seen["cid"] == "c1" and seen["rnd"] == 2 and seen["ad"].body == "Hi"

        def boom(*a, **k):
            raise RuntimeError("db down")

        monkeypatch.setattr(node, "run_for_round", boom)
        assert node.crash_test_node({"campaign_id": "c1", "round_id": 2, "creative": creative}) == {}

    def test_the_graph_runs_it_between_the_focus_group_and_gate_2(self):
        from src.graph.build_graph import build_graph

        edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
        assert ("focus_group", "crash_test") in edges and ("crash_test", "gate_2") in edges


class FakeClient:
    """Just enough of the Supabase client for apply_revision."""

    def __init__(self, tables):
        self.tables, self.inserts, self.updates = tables, [], []

    def table(self, name):
        return FakeQuery(self, name)


class FakeQuery:
    def __init__(self, db, name):
        self.db, self.name, self.filters, self.op, self.payload = db, name, {}, "select", None

    def select(self, *a):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def limit(self, *a):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, row):
        self.op, self.payload = "update", row
        return self

    def execute(self):
        if self.op == "insert":
            self.db.inserts.append((self.name, self.payload))
            return type("R", (), {"data": [self.payload]})()
        if self.op == "update":
            self.db.updates.append((self.name, self.payload, dict(self.filters)))
            return type("R", (), {"data": [self.payload]})()
        rows = [r for r in self.db.tables.get(self.name, []) if all(r.get(k) == v for k, v in self.filters.items())]
        data = rows[0] if getattr(self, "single", False) else rows
        return type("R", (), {"data": data or (None if getattr(self, "single", False) else [])})() if data or not getattr(self, "single", False) else None


class TestApplyRevision:
    @pytest.fixture
    def db(self, monkeypatch):
        from src.scheduler import run_capability as rc

        report = {"revised": {"body": "Step off the metro and your coffee is waiting.", "headline": "Coffee on arrival", "cta": "Order now"}}
        client = FakeClient({
            "campaigns": [{"id": "c1", "org_id": "o1", "status": "awaiting_gate_2", "current_round": 1}],
            "memberships": [{"org_id": "o1", "user_id": "u1", "role": "approver"}, {"org_id": "o1", "user_id": "u2", "role": "viewer"}],
            "crash_tests": [{"id": "t1", "campaign_id": "c1", "round_number": 1, "report": report, "applied_at": None}],
            "iterations": [{"campaign_id": "c1", "round_number": 1, "copy_text": "Rahul says…", "headline": "Old", "cta": "Order Now",
                            "template": "centered_hero", "ad_slots": {}, "image_version": 0}],
            "copy_revisions": [],
        })
        monkeypatch.setattr(rc, "get_client", lambda: client)
        monkeypatch.setattr("src.capabilities.product.product_for_campaign", lambda cid: type("P", (), {"cutout": b"png"})())
        monkeypatch.setattr("src.capabilities.brand.brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr("src.tools.ad_templates.compose_product_ad", lambda *a, **k: b"jpg")
        monkeypatch.setattr("src.db.supabase_client.upload_ad_image", lambda cid, rnd, data, **k: f"{cid}/round-{rnd}.jpg")
        return rc, client

    def test_an_approver_applies_it_with_history_and_a_redrawn_ad(self, db):
        rc, client = db
        out = rc._run_apply_revision({"campaign_id": "c1", "round": 1, "crash_test_id": "t1"}, "u1")
        assert out["copy_applied"] and out["image_redrawn"]
        revisions = [row["copy_text"] for name, row in client.inserts if name == "copy_revisions"]
        assert revisions == ["Rahul says…", "Step off the metro and your coffee is waiting."]  # original kept as version 1
        iteration = next(p for n, p, f in client.updates if n == "iterations")
        assert iteration["headline"] == "Coffee on arrival" and iteration["image_version"] == 1
        assert any(n == "crash_tests" and p.get("applied_by") == "u1" for n, p, f in client.updates)

    def test_only_approvers_and_only_at_gate_2(self, db):
        rc, client = db
        with pytest.raises(PermissionError):
            rc._run_apply_revision({"campaign_id": "c1", "round": 1, "crash_test_id": "t1"}, "u2")
        client.tables["campaigns"][0]["status"] = "awaiting_metrics"
        with pytest.raises(ValueError):
            rc._run_apply_revision({"campaign_id": "c1", "round": 1, "crash_test_id": "t1"}, "u1")

    def test_an_applied_revision_cant_be_applied_twice(self, db):
        rc, client = db
        client.tables["crash_tests"][0]["applied_at"] = "2026-10-25T00:00:00Z"
        with pytest.raises(ValueError, match="already applied"):
            rc._run_apply_revision({"campaign_id": "c1", "round": 1, "crash_test_id": "t1"}, "u1")


def test_tools_crash_test_needs_ad_text(monkeypatch):
    from src.scheduler import run_capability as rc

    with pytest.raises(ValueError):
        rc._run_crash_test({"idea": IDEA, "copy": "  "}, "u1")
    fake_llm(monkeypatch, {"scenarios": []})
    out = rc._run_crash_test({"idea": IDEA, "copy": CLEAN.body, "headline": CLEAN.headline}, "u1")
    assert out["simulation_only"] and out["risk"] in ("clear", "low")


def test_a_revision_that_grew_is_asked_again_shorter(monkeypatch):
    long = {**REVISED, "copy": REVISED["copy"] + " Available at major stations and office hubs, based on our average timing data." * 2}
    llm = fake_llm(monkeypatch, long, REVISED)
    revised, _ = ct.revise(COFFEE, rule_checks(COFFEE, idea=IDEA), idea=IDEA)
    assert revised.body == REVISED["copy"] and len(llm.prompts) == 2 and "Make it shorter" in llm.prompts[1]
