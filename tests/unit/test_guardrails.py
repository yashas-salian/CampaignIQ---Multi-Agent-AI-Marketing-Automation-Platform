import pytest

from src.capabilities import creative as creative_mod
from src.capabilities.audience import Persona
from src.capabilities.guardrails import check_creative, prepare_for_channel
from src.graph.nodes import distribution_bluesky, distribution_email

PERSONA = Persona(
    name="Ava", demographics="d", psychographics="p", channel_fit="email",
    messaging_angle="m", age_bracket="25-34", income_tier="mid",
)


def codes(result, severity):
    return [i.code for i in result.issues if i.severity == severity]


class TestChecks:
    def test_clean_copy_passes(self):
        result = check_creative("Fresh spice kits from home cooks, delivered weekly.", channels=["bluesky", "email"])
        assert result.ok and result.issues == []

    def test_links_other_than_the_cta_are_blocked(self):
        assert codes(check_creative("Claim yours at free-prizes.xyz now"), "block") == ["foreign_link"]
        assert check_creative("Order at shop.spicekits.com/today", cta_url="https://spicekits.com").ok
        assert not check_creative("Visit https://spicekits.com.evil.io", cta_url="https://spicekits.com").ok

    def test_personal_data_is_blocked(self):
        assert "personal_data" in codes(check_creative("Email me at ava@example.com"), "block")
        assert "personal_data" in codes(check_creative("Call +1 (415) 555-0134 today"), "block")
        assert check_creative("Save 20% on 3 boxes in 2026").ok  # numbers aren't phone numbers

    def test_banned_terms_whole_words_only(self, monkeypatch):
        monkeypatch.setenv("BANNED_TERMS", "cheap, knockoff")
        assert codes(check_creative("Not a cheap knockoff"), "block") == ["banned_term", "banned_term"]
        assert check_creative("Cheaper than takeout").ok
        assert codes(check_creative("Our rival brand", banned_terms=["rival"]), "block") == ["banned_term"]

    def test_bluesky_length_only_when_posting_there(self):
        long = "x" * 301
        assert codes(check_creative(long, channels=["bluesky"]), "block") == ["too_long"]
        assert check_creative(long, channels=["email"]).ok

    def test_regulated_claims_need_review_and_get_a_disclaimer(self):
        health = check_creative("Our tea cures insomnia, guaranteed.", domain_category="healthcare")
        assert health.ok  # review, not block
        assert len(codes(health, "review")) == 2 and "medical advice" in health.disclaimer
        finance = check_creative("Earn 12% returns with zero risk", domain_category="finance_fintech")
        assert codes(finance, "review") and "financial advice" in finance.disclaimer
        assert check_creative("Cures boredom", domain_category="entertainment_media").needs_review == []


class TestSendTime:
    def test_short_disclaimer_added_on_bluesky_when_it_fits(self):
        text, reason = prepare_for_channel("Sleep better tonight.", "bluesky", domain_category="healthcare")
        assert reason is None and text.endswith("Not medical advice.")
        long = "y" * 290
        assert prepare_for_channel(long, "bluesky", domain_category="healthcare")[0] == long

    def test_blocked_copy_is_not_sent(self, monkeypatch):
        monkeypatch.setattr(distribution_bluesky, "post_bluesky", lambda *a, **k: pytest.fail("sent blocked copy"))
        saved = {}
        monkeypatch.setattr(distribution_bluesky, "upsert_iteration", lambda *a, **k: saved.update(k))
        state = {
            "campaign_id": "c1", "user_id": "u1", "round_id": 1, "domain_category": "other",
            "creative": type("C", (), {"copy_text": "Win big at scam.xyz", "image_bytes": b""})(),
        }
        out = distribution_bluesky.distribution_bluesky_node(state)
        assert out["bluesky_post_uri"].startswith("dead: blocked by brand-safety checks")
        assert saved["bluesky_post_uri"] == out["bluesky_post_uri"]

    def test_email_carries_the_full_disclaimer(self, monkeypatch):
        sent = {}
        monkeypatch.setattr(distribution_email, "send_campaign_email", lambda *a, **k: sent.update(k) or "DRY_RUN")
        monkeypatch.setattr(distribution_email, "upsert_iteration", lambda *a, **k: None)
        state = {
            "campaign_id": "c1", "user_id": "u1", "round_id": 1, "domain_category": "finance_fintech",
            "idea": "Round-up investing", "email_to": ["a@x.io"],
            "creative": type("C", (), {"copy_text": "Invest your spare change.", "image_bytes": b"", "headline": ""})(),
        }
        distribution_email.distribution_email_node(state)
        assert "not financial advice" in sent["html"].lower()


class TestGenerateCreative:
    @pytest.fixture
    def wired(self, monkeypatch, fake_llm):
        monkeypatch.setattr(creative_mod, "select_arm_for_campaign", lambda *a: (3, "minimalist", "direct_factual"))

        class Images:
            supports_outpainting = False

            def generate_image(self, prompt):
                return b"img"

        monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Images())

        def use(*replies):
            llm = fake_llm(*replies)
            monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)
            return llm

        return use

    def test_blocked_draft_is_rewritten_with_the_reasons(self, wired):
        llm = wired(
            '{"copy": "Grab it at deals.xyz", "image_prompt": "a"}',
            '{"copy": "Spice kits, delivered weekly.", "image_prompt": "b"}',
        )
        result = creative_mod.generate_creative("Spice kits", PERSONA, domain_category="food_beverage", active_channels=["bluesky"])
        assert result.copy_text == "Spice kits, delivered weekly." and result.guardrails.ok
        assert "rejected by brand-safety checks" in llm.prompts[1] and "deals.xyz" in llm.prompts[1]

    def test_gives_up_after_the_rewrite_budget_and_keeps_the_least_bad(self, wired):
        llm = wired('{"copy": "Grab it at deals.xyz", "image_prompt": "a"}')
        result = creative_mod.generate_creative("x", PERSONA, domain_category="other", active_channels=["email"])
        assert len(llm.prompts) == 1 + creative_mod.MAX_GUARDRAIL_REWRITES
        assert not result.guardrails.ok  # surfaced at Gate 2; distribution will refuse it
