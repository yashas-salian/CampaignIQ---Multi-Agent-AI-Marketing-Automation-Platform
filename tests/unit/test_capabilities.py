import pytest

from src.capabilities import distribution, feasibility, idea_intake
from src.capabilities.feedback_correction import build_campaign_summary, run_feedback_correction
from src.capabilities.metrics import MetricsResult
from src.providers.free.groq_llm import GroqLLMProvider


class TestIdeaIntake:
    def test_free_tier_uses_local_model_without_an_llm_call(self, monkeypatch, fake_llm):
        groq = GroqLLMProvider()
        monkeypatch.setattr(idea_intake, "get_llm", lambda user_id=None: groq)
        monkeypatch.setattr("src.providers.free.local_domain_classifier.classify_domain", lambda idea: "education")
        monkeypatch.setattr(groq, "generate", lambda *a, **k: pytest.fail("LLM must not be called"))
        assert idea_intake.normalize_idea("  A tutoring app ").model_dump() == {
            "idea": "A tutoring app",
            "domain_category": "education",
        }

    def test_falls_back_to_llm_when_local_model_unavailable(self, monkeypatch):
        groq = GroqLLMProvider()
        monkeypatch.setattr(idea_intake, "get_llm", lambda user_id=None: groq)
        monkeypatch.setattr("src.providers.free.local_domain_classifier.classify_domain", lambda idea: None)
        monkeypatch.setattr(groq, "generate", lambda *a, **k: '{"domain_category": "real_estate"}')
        assert idea_intake.normalize_idea("Rent-to-own homes").domain_category == "real_estate"

    def test_paid_llm_skips_local_model(self, monkeypatch, fake_llm):
        monkeypatch.setattr(idea_intake, "get_llm", lambda user_id=None: fake_llm('{"domain_category": "healthcare"}'))
        monkeypatch.setattr(
            "src.providers.free.local_domain_classifier.classify_domain", lambda idea: pytest.fail("not for paid")
        )
        assert idea_intake.normalize_idea("Telehealth for pets").domain_category == "healthcare"

    def test_use_local_false_forces_the_teacher(self, monkeypatch):
        groq = GroqLLMProvider()
        monkeypatch.setattr(idea_intake, "get_llm", lambda user_id=None: groq)
        monkeypatch.setattr(
            "src.providers.free.local_domain_classifier.classify_domain", lambda idea: pytest.fail("teacher only")
        )
        monkeypatch.setattr(groq, "generate", lambda *a, **k: '{"domain_category": "other"}')
        assert idea_intake.normalize_idea("x", use_local=False).domain_category == "other"


class TestFeasibility:
    def _patch_signals(self, monkeypatch, fake_llm, *, news=None, bluesky=None):
        llm = fake_llm('{"keywords_en": "meal kits", "keywords_localized": "kits de comida"}', "Momentum is moderate.")
        monkeypatch.setattr(feasibility, "get_llm", lambda user_id=None: llm)
        monkeypatch.setattr(feasibility, "get_trend_interest", lambda kw, hl: {"keyword": kw, "mean_interest": 50})
        monkeypatch.setattr(
            feasibility, "get_news_volume", news or (lambda kw, language: {"total_results": 30, "headlines": []})
        )
        monkeypatch.setattr(
            feasibility, "search_bluesky", bluesky or (lambda kw: {"result_count": 4, "avg_score": 10.0, "avg_comments": 1})
        )
        return llm

    def test_composite_is_the_weighted_signal_sum(self, monkeypatch, fake_llm):
        self._patch_signals(monkeypatch, fake_llm)
        result = feasibility.score_feasibility("Meal kits for students")
        assert result.score == round(0.4 * 50 + 0.3 * 30 + 0.3 * 10)
        assert result.rationale == "Momentum is moderate."
        assert set(result.signals) == {"trend", "news", "bluesky"}

    def test_a_failing_signal_degrades_to_neutral_instead_of_crashing(self, monkeypatch, fake_llm):
        def boom(kw, language):
            raise TimeoutError("newsapi down")

        self._patch_signals(monkeypatch, fake_llm, news=boom)
        result = feasibility.score_feasibility("Meal kits")
        assert result.signals["news"]["error"] == "newsapi down"
        assert result.score == round(0.4 * 50 + 0.3 * 10)

    def test_localized_keywords_drive_the_search(self, monkeypatch, fake_llm):
        seen = []
        self._patch_signals(monkeypatch, fake_llm, bluesky=lambda kw: seen.append(kw) or {"avg_score": 0.0})
        feasibility.score_feasibility("Meal kits", target_language="es")
        assert seen == ["kits de comida"]

    def test_mastodon_only_counts_with_a_token(self, monkeypatch, fake_llm):
        self._patch_signals(monkeypatch, fake_llm)
        monkeypatch.setattr(feasibility, "search_mastodon", lambda kw: {"avg_score": 90.0})
        assert "mastodon" not in feasibility.score_feasibility("x").signals

        self._patch_signals(monkeypatch, fake_llm)
        monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "t")
        result = feasibility.score_feasibility("x")
        assert result.score == round(0.4 * 50 + 0.3 * 30 + 0.3 * (10 + 90) / 2)


class TestDistribution:
    def test_dry_run_never_calls_the_channel(self, monkeypatch):
        monkeypatch.setattr(distribution, "post_to_bluesky", lambda *a, **k: pytest.fail("real post in DRY_RUN"))
        assert distribution.post_bluesky("c1", 1, "Hello world").startswith("DRY_RUN: would post to Bluesky")

    def test_same_round_is_sent_once(self):
        distribution.post_bluesky("c1", 1, "Hello")
        assert distribution.post_bluesky("c1", 1, "Hello").startswith("skipped")
        assert distribution.post_bluesky("c1", 2, "Hello").startswith("DRY_RUN")

    def test_live_send_when_dry_run_is_off(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **_: f"email-id-for-{len(to)}")
        assert distribution.send_campaign_email("c2", 1, ["a@x.io", "b@x.io"], "Hi", "<p>x</p>") == "email-id-for-2"

    def test_cta_link_is_click_tracked_when_configured(self, monkeypatch):
        sent = {}
        monkeypatch.setenv("DRY_RUN", "false")
        monkeypatch.setenv("TRACK_CLICK_BASE_URL", "https://ref.supabase.co/functions/v1/track-click")
        monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **_: sent.setdefault("html", html))
        distribution.send_campaign_email("c3", 2, ["a@x.io"], "Hi", "<p>x</p>", cta_url="https://shop.io/a?b=1")
        assert "track-click?url=https%3A%2F%2Fshop.io%2Fa%3Fb%3D1&campaign_id=c3&round_id=2&channel=email" in sent["html"]


class TestFeedbackCorrection:
    def test_round_cap_stops_without_an_llm_call(self, monkeypatch):
        monkeypatch.setattr("src.capabilities.feedback_correction.get_llm", lambda *a: pytest.fail("no LLM at cap"))
        metrics = MetricsResult(channel_rewards={}, overall_reward=0.9, raw={})
        directive = run_feedback_correction("idea", metrics, current_round=3, max_rounds=3)
        assert directive.continue_campaign is False

    def test_unmeasured_round_continues_without_an_llm_call(self, monkeypatch):
        # DRY_RUN (or every delivery failed): no channel was measured. That is no
        # signal, so the campaign must not be stopped as if it scored zero.
        monkeypatch.setattr("src.capabilities.feedback_correction.get_llm", lambda *a: pytest.fail("no LLM without data"))
        metrics = MetricsResult(channel_rewards={}, overall_reward=0.0, raw={})
        directive = run_feedback_correction("idea", metrics, current_round=1, max_rounds=3)
        assert directive.continue_campaign is True

    def test_zero_engagement_everywhere_continues_without_an_llm_call(self, monkeypatch):
        # Seen in production: a new account's first round got 0 on every channel
        # and the model stopped the campaign as a failure after round 1.
        monkeypatch.setattr("src.capabilities.feedback_correction.get_llm", lambda *a: pytest.fail("no LLM on all zeros"))
        metrics = MetricsResult(channel_rewards={"bluesky": 0.0, "mastodon": 0.0, "email": 0.0}, overall_reward=0.0, raw={})
        directive = run_feedback_correction("idea", metrics, current_round=1, max_rounds=3)
        assert directive.continue_campaign is True and directive.adjustments

    def test_zero_engagement_at_the_round_cap_still_stops(self, monkeypatch):
        monkeypatch.setattr("src.capabilities.feedback_correction.get_llm", lambda *a: pytest.fail("no LLM at cap"))
        metrics = MetricsResult(channel_rewards={"email": 0.0}, overall_reward=0.0, raw={})
        assert run_feedback_correction("idea", metrics, current_round=3, max_rounds=3).continue_campaign is False

    def test_some_engagement_asks_the_model(self, monkeypatch, fake_llm):
        monkeypatch.setattr(
            "src.capabilities.feedback_correction.get_llm",
            lambda *a: fake_llm('{"continue_campaign": false, "reasoning": "weak", "adjustments": ""}'),
        )
        metrics = MetricsResult(channel_rewards={"email": 0.0, "bluesky": 0.04}, overall_reward=0.02, raw={})
        assert run_feedback_correction("idea", metrics, current_round=1, max_rounds=3).continue_campaign is False

    def test_summary_aggregates_rewards_and_engagement(self, monkeypatch):
        monkeypatch.setattr("src.db.supabase_client.get_all_iterations", lambda cid: [{}, {}])
        monkeypatch.setattr(
            "src.db.supabase_client.get_all_metrics",
            lambda cid: [
                {"round_number": 1, "reward": 0.2, "channel": "bluesky", "raw_metrics": {"likes": 3, "uri": "at://x"}},
                {"round_number": 1, "reward": 0.4, "channel": "email", "raw_metrics": {"clicks": 2}},
                {"round_number": 2, "reward": 0.8, "channel": "bluesky", "raw_metrics": {"likes": 7}},
            ],
        )
        summary = build_campaign_summary("c1")
        assert summary["total_rounds"] == 2
        assert summary["reward_trend"] == [{"round": 1, "reward": pytest.approx(0.3)}, {"round": 2, "reward": 0.8}]
        assert summary["winning_round"]["round"] == 2
        assert summary["total_engagement"] == {"bluesky_likes": 10, "email_clicks": 2}
