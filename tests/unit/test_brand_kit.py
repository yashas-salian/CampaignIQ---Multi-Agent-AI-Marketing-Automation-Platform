from src.capabilities import creative as creative_mod
from src.capabilities.audience import Persona
from src.capabilities.brand import BrandKit, with_required_phrase

PERSONA = Persona(name="Ava", demographics="d", psychographics="p", channel_fit="email", messaging_angle="m",
                  age_bracket="25-34", income_tier="mid")
KIT = BrandKit(voice="Warm, plain-spoken, never salesy.", preferred_words=["home-cooked"], forbidden_words=["cheap"],
               required_phrase="#CookHappy")


def test_empty_kit_adds_nothing():
    assert BrandKit().prompt_section() == ""


def test_kit_section_fences_the_voice_and_lists_rules():
    section = KIT.prompt_section()
    assert '<untrusted source="brand_voice"' in section and "Warm, plain-spoken" in section
    assert "Prefer these words where natural: home-cooked" in section
    assert "Never use these words: cheap" in section and 'End the copy with: "#CookHappy"' in section


def test_required_phrase_is_appended_once_and_only_if_it_fits():
    assert with_required_phrase("Dinner, sorted.", KIT) == "Dinner, sorted. #CookHappy"
    assert with_required_phrase("Dinner, sorted. #cookhappy", KIT) == "Dinner, sorted. #cookhappy"
    assert with_required_phrase("x" * 295, KIT, max_len=300) == "x" * 295
    assert with_required_phrase("Hi", None) == "Hi"


def test_creative_follows_the_kit_and_its_forbidden_words_block(monkeypatch, fake_llm):
    llm = fake_llm('{"copy": "A cheap way to eat well.", "image_prompt": "a"}', '{"copy": "Home-cooked, ready tonight.", "image_prompt": "b"}')
    monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)
    monkeypatch.setattr(creative_mod, "select_arm_for_campaign", lambda *a: (0, "minimalist", "direct_factual"))

    class Img:
        supports_outpainting = False

        def generate_image(self, p):
            return b"i"

    monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Img())
    result = creative_mod.generate_creative("Meal kits", PERSONA, domain_category="food_beverage", active_channels=["email"], brand=KIT)
    assert "Brand guidelines" in llm.prompts[0]
    assert 'banned term "cheap"' in llm.prompts[1]  # rewritten because of the kit
    assert result.copy_text == "Home-cooked, ready tonight."
