"""A template picked in the campaign composer holds for every round: the
arm keeps its style, variant B uses it too, and it's drawn as chosen."""
import io
import json
from types import SimpleNamespace

from PIL import Image

from src.capabilities import creative as creative_mod
from src.capabilities.audience import Persona
from src.capabilities.creative import Creative, arm_for_template
from src.graph.nodes import creative as creative_node_mod
from src.graph.nodes import variant_b as variant_b_mod
from src.tools.bandit import ARMS
from tests.conftest import FakeLLM

PERSONA = Persona(
    name="Priya", demographics="24, Pune", psychographics="runs every morning", channel_fit="bluesky",
    messaging_angle="hydration", age_bracket="18-24", income_tier="mid",
)
# Best first, as the bandit ranks them: two minimalist arms, then two bold-promo ones.
RANKED = [(1, "minimalist", "urgency_scarcity"), (0, "minimalist", "direct_factual"),
          (13, "urgency_scarcity", "urgency_scarcity"), (12, "urgency_scarcity", "direct_factual")]


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (300, 600), (200, 140, 20, 255)).save(out, format="PNG")
    return out.getvalue()


class TestArmForTemplate:
    def test_the_best_arm_of_the_templates_style(self):
        assert arm_for_template("diagonal_flash", RANKED) == (13, "urgency_scarcity", "urgency_scarcity")

    def test_a_preferred_arm_of_that_style_is_kept(self):
        assert arm_for_template("diagonal_flash", RANKED, (12, "urgency_scarcity", "direct_factual"))[0] == 12

    def test_a_preferred_arm_of_another_style_gives_way(self):
        assert arm_for_template("diagonal_flash", RANKED, (1, "minimalist", "urgency_scarcity"))[1] == "urgency_scarcity"

    def test_with_nothing_ranked_it_is_still_a_real_arm_of_that_style(self):
        index, style, tone = arm_for_template("dark_glow", [])
        assert style == "lifestyle_aspirational" and ARMS[index] == (style, tone)


def test_a_chosen_template_is_drawn_even_without_its_extra_words(monkeypatch):
    # big_number needs a number from the idea; the brief has none and the LLM gave none.
    llm = FakeLLM(json.dumps({"copy": "Cold and calm.", "headline": "Instant hydration", "cta": "Drink now",
                              "template": "big_number", "slots": {}, "image_prompt": ""}))
    monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)
    monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: SimpleNamespace(supports_outpainting=False))
    result = creative_mod.generate_creative(
        "Cold electrolyte drink", PERSONA, domain_category="food_beverage", active_channels=["bluesky"],
        product_cutout=_png(), template="big_number", arm=(4, "testimonial_social_proof", "direct_factual"),
    )
    assert result.template == "big_number"
    assert "- big_number:" in llm.prompts[0] and "- benefit_checklist:" not in llm.prompts[0]


def _creative(style="urgency_scarcity", tone="urgency_scarcity", arm=13):
    return Creative(copy_text="x", image_prompt="y", image_bytes=b"", image_style=style, copy_tone=tone, arm_index=arm)


def _patch_nodes(monkeypatch, template, seen):
    product = SimpleNamespace(cutout=b"png", tagline="", template=template)
    for mod in (creative_node_mod, variant_b_mod):
        monkeypatch.setattr(mod, "product_for_campaign", lambda cid: product)
        monkeypatch.setattr(mod, "brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr(mod, "generate_creative", lambda *a, **k: seen.append(k) or _creative())
    monkeypatch.setattr(creative_node_mod, "playbook_section_for_campaign", lambda cid: "")
    monkeypatch.setattr(creative_node_mod, "recall", lambda ctx: SimpleNamespace(section="", directives={}))
    monkeypatch.setattr(creative_node_mod, "_candidate_arms", lambda state: RANKED)
    monkeypatch.setattr(creative_node_mod, "active_channels", lambda: ["bluesky", "email"])
    monkeypatch.setattr(variant_b_mod, "active_channels", lambda: ["bluesky", "email"])
    monkeypatch.setattr(variant_b_mod, "select_arms_for_campaign", lambda *a, k=2: RANKED[:k])
    monkeypatch.setattr(variant_b_mod, "upsert_iteration", lambda *a, **k: None)


STATE = {"idea": "Cold drink", "primary_persona": PERSONA, "domain_category": "food_beverage", "campaign_id": "c1",
         "user_id": "u1", "round_id": 1, "ab_test": True, "email_to": ["a@x.co", "b@x.co"]}


def test_every_round_uses_the_creators_template_in_its_style(monkeypatch):
    seen = []
    _patch_nodes(monkeypatch, "diagonal_flash", seen)
    creative_node_mod.creative_node(dict(STATE))
    assert seen[0]["template"] == "diagonal_flash" and seen[0]["arm"] == (13, "urgency_scarcity", "urgency_scarcity")


def test_an_ab_winner_of_another_style_still_keeps_the_template(monkeypatch):
    seen = []
    _patch_nodes(monkeypatch, "diagonal_flash", seen)
    creative_node_mod.creative_node({**STATE, "promote_arm": (1, "minimalist", "urgency_scarcity")})
    assert seen[0]["arm"][1] == "urgency_scarcity" and seen[0]["template"] == "diagonal_flash"


def test_variant_b_uses_the_template_with_the_second_best_tone_in_its_style(monkeypatch):
    seen = []
    _patch_nodes(monkeypatch, "diagonal_flash", seen)
    variant_b_mod.generate_variant_b_node(dict(STATE))
    assert seen[0]["template"] == "diagonal_flash" and seen[0]["arm"] == (12, "urgency_scarcity", "direct_factual")


def test_without_a_chosen_template_the_bandit_and_llm_choose_as_before(monkeypatch):
    seen = []
    _patch_nodes(monkeypatch, "", seen)
    creative_node_mod.creative_node(dict(STATE))
    variant_b_mod.generate_variant_b_node(dict(STATE))
    assert seen[0]["template"] is None and seen[0]["arm"] is None
    assert seen[1]["template"] is None and seen[1]["arm"] == RANKED[1]


def test_an_unknown_stored_template_is_ignored(monkeypatch):
    from src.capabilities import product as product_mod

    row = {"product_image_path": None, "product_tagline": "", "ad_template": "not_a_template"}
    query = SimpleNamespace()
    query.select = query.eq = query.maybe_single = lambda *a, **k: query
    query.execute = lambda: SimpleNamespace(data=row)
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: SimpleNamespace(table=lambda name: query))
    assert product_mod.product_for_campaign("c1").template == ""
    row["ad_template"] = "rings_orbit"
    assert product_mod.product_for_campaign("c1").template == "rings_orbit"
