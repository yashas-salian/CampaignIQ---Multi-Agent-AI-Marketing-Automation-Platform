"""Ad composer, Gemini image provider with Pollinations fallback, and the
creative step that ties them together."""
import base64
import io

import pytest
from PIL import Image

from src.capabilities import creative as creative_mod
from src.capabilities.audience import Persona
from src.capabilities.brand import BrandKit
from src.providers.free import gemini_image, hf_image
from src.providers.free.gemini_image import FallbackImageProvider, GeminiImageProvider, _find_image
from src.providers.free.hf_image import HuggingFaceImageProvider
from src.tools.ad_composer import SIZES, _ink_on, _rgb, can_set, compose_ad

PERSONA = Persona(
    name="Maya", demographics="32, Denver", psychographics="weekend hiker", channel_fit="bluesky",
    messaging_angle="lighter packs", age_bracket="25-34", income_tier="mid",
)


def _picture(width=1024, height=768, color=(40, 120, 200)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, format="PNG")
    return out.getvalue()


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class TestComposeAd:
    def test_square_ad_is_a_jpeg_at_feed_size_with_text_drawn(self):
        bare = compose_ad(_picture())
        ad = compose_ad(_picture(), "Lighter packs for long trails", "Shop now", brand_color="#1f6feb")
        image = _open(ad)
        assert image.format == "JPEG" and image.size == (1080, 1080)
        # The scrim, headline and button change the lower part, not the top.
        assert _open(bare).crop((0, 0, 1080, 300)).tobytes() == image.crop((0, 0, 1080, 300)).tobytes()
        assert _open(bare).crop((0, 700, 1080, 1080)).tobytes() != image.crop((0, 700, 1080, 1080)).tobytes()

    def test_banner_format_and_cover_crop(self):
        assert _open(compose_ad(_picture(500, 900), "Hola", "Pide ya", fmt="banner")).size == (1200, 628)

    def test_cta_button_uses_the_brand_colour(self):
        ad = _open(compose_ad(_picture(color=(255, 255, 255)), "", "Book a table", brand_color="#00aa55"))
        r, g, b = ad.convert("RGB").getpixel((84, 972))  # pill: x from 70, y 935-1010; left of the label
        assert g > r + 60 and g > b + 40

    def test_unsettable_scripts_are_left_off_not_drawn_as_boxes(self):
        assert not can_set("हर दिन ताज़ा") and not can_set("Fresh 🌿") and can_set("Café, ¿listo? 20 €")
        bare = compose_ad(_picture())
        assert compose_ad(_picture(), "हर दिन ताज़ा", "अभी खरीदें") == bare

    def test_long_headlines_are_clipped_and_bad_colours_default(self):
        compose_ad(_picture(), "word " * 60, "a very long call to action label indeed")  # no error
        assert _rgb("nonsense") == _rgb("#ff6b3d") and _rgb("#abc") == (0xAA, 0xBB, 0xCC)
        assert _ink_on((255, 220, 0)) == (17, 19, 22) and _ink_on((20, 40, 120)) == (255, 255, 255)


class _Response:
    def __init__(self, status, body=None, content=b"", content_type="application/json"):
        self.status_code, self._body, self.content = status, body or {}, content
        self.headers = {"content-type": content_type}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestGemini:
    @pytest.fixture(autouse=True)
    def reset(self, monkeypatch):
        monkeypatch.setattr(GeminiImageProvider, "disabled_reason", None)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    def test_finds_the_image_in_either_response_shape(self):
        data = base64.b64encode(b"img").decode()
        assert _find_image({"output_image": {"data": data}}) == data
        steps = {"steps": [{"type": "thought"}, {"type": "model_output", "content": [{"type": "text", "text": "x"}, {"type": "image", "data": data}]}]}
        assert _find_image(steps) == data and _find_image({"steps": []}) is None

    def test_request_shape_and_decoding(self, monkeypatch):
        sent = {}

        def post(url, headers, json, timeout):
            sent.update(url=url, headers=headers, json=json)
            return _Response(200, {"steps": [{"type": "model_output", "content": [{"type": "image", "data": base64.b64encode(b"jpg").decode()}]}]})

        monkeypatch.setattr(gemini_image.requests, "post", post)
        assert GeminiImageProvider().generate_image("a bike") == b"jpg"
        assert sent["url"].endswith("/v1beta/interactions") and sent["headers"]["x-goog-api-key"] == "test-key"
        assert sent["json"]["model"] == gemini_image.DEFAULT_MODEL
        assert sent["json"]["response_format"]["aspect_ratio"] == "1:1"

    def test_no_billing_disables_gemini_for_the_process(self, monkeypatch):
        calls = []
        monkeypatch.setattr(gemini_image.requests, "post", lambda *a, **k: calls.append(1) or _Response(429))
        provider = GeminiImageProvider()
        with pytest.raises(RuntimeError):
            provider.generate_image("x")
        with pytest.raises(RuntimeError, match="unavailable"):
            provider.generate_image("x")
        assert len(calls) == 1

    def test_fallback_moves_on_and_only_raises_when_all_fail(self):
        class Broken:
            def generate_image(self, prompt):
                raise RuntimeError("down")

        class Works:
            def generate_image(self, prompt):
                return b"ok"

        assert FallbackImageProvider([Broken(), Works()]).generate_image("x") == b"ok"
        with pytest.raises(RuntimeError, match="down"):
            FallbackImageProvider([Broken(), Broken()]).generate_image("x")

    def test_free_tier_chain_is_flux_then_gemini_then_pollinations(self, monkeypatch):
        from src.providers import registry
        from src.providers.free.pollinations_image import PollinationsImageProvider

        for key in ("PAID_IMAGE_API_KEY", "PAID_LLM_API_KEY", "FORCE_FREE_TIER"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HF_TOKEN", "hf-test")
        chain = registry.get_image_generator()._providers
        assert [type(p) for p in chain] == [HuggingFaceImageProvider, GeminiImageProvider, PollinationsImageProvider]
        monkeypatch.delenv("HF_TOKEN")
        monkeypatch.delenv("GEMINI_API_KEY")
        assert isinstance(registry.get_image_generator(), PollinationsImageProvider)


class TestHuggingFace:
    @pytest.fixture(autouse=True)
    def reset(self, monkeypatch):
        monkeypatch.setattr(HuggingFaceImageProvider, "disabled_reason", None)
        monkeypatch.setenv("HF_TOKEN", "hf-test")

    def _client(self, monkeypatch, behaviour):
        import huggingface_hub

        made = []

        class Client:
            def __init__(self, **kwargs):
                made.append(kwargs)

            def text_to_image(self, prompt, **kwargs):
                made.append({"prompt": prompt, **kwargs})
                return behaviour()

        monkeypatch.setattr(huggingface_hub, "InferenceClient", Client)
        return made

    def test_asks_flux_through_the_auto_provider_and_returns_a_jpeg(self, monkeypatch):
        made = self._client(monkeypatch, lambda: Image.new("RGB", (1024, 1024), (10, 200, 10)))
        data = HuggingFaceImageProvider().generate_image("a bike")
        assert _open(data).format == "JPEG"
        assert made[0]["provider"] == "auto" and made[0]["api_key"] == "hf-test"
        assert made[1]["prompt"] == "a bike" and made[1]["model"] == hf_image.DEFAULT_MODEL

    def test_out_of_credit_disables_it_for_the_process(self, monkeypatch):
        class OutOfCredit(Exception):
            response = type("R", (), {"status_code": 402})()

        def fail():
            raise OutOfCredit("no remaining credits")

        made = self._client(monkeypatch, fail)
        for _ in range(2):
            with pytest.raises(Exception):
                HuggingFaceImageProvider().generate_image("x")
        assert len([m for m in made if "prompt" in m]) == 1


def test_pollinations_watermark_strip_is_cut_off(monkeypatch):
    from src.providers.free import pollinations_image

    asked = {}

    def fake(prompt, width, height, seed=None):
        asked.update(width=width, height=height)
        img = Image.new("RGB", (width, height), (0, 0, 255))
        img.paste((255, 0, 0), (0, height - pollinations_image.WATERMARK_STRIP, width, height))  # the "watermark"
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    monkeypatch.setattr(pollinations_image, "generate_pollinations_image", fake)
    image = _open(pollinations_image.PollinationsImageProvider().generate_image("x")).convert("RGB")
    assert asked["height"] > asked["width"] and image.size == (1024, 1024)
    r, g, b = image.getpixel((1000, 1020))
    assert b > 200 and r < 60


class TestCreativeAd:
    @pytest.fixture
    def wired(self, monkeypatch, fake_llm):
        prompts = []

        class Images:
            supports_outpainting = False

            def generate_image(self, prompt):
                prompts.append(prompt)
                return _picture()

        monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Images())
        monkeypatch.setattr(creative_mod, "select_arm_for_campaign", lambda *a: (0, "minimalist", "direct_factual"))

        def use(reply):
            llm = fake_llm(reply)
            monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)
            return prompts

        return use

    def test_headline_and_cta_are_set_on_the_image(self, wired):
        prompts = wired('{"copy": "Trail-ready in minutes.", "headline": "Half the weight", "cta": "Shop now", "image_prompt": "a hiker"}')
        result = creative_mod.generate_creative("Light packs", PERSONA, domain_category="retail", active_channels=["bluesky"])
        assert (result.headline, result.cta) == ("Half the weight", "Shop now")
        assert _open(result.image_bytes).size == (1080, 1080)
        assert prompts[0].startswith("a hiker") and "no text" in prompts[0]

    def test_banned_words_drop_the_headline(self, wired):
        wired('{"copy": "Trail-ready in minutes.", "headline": "Cheap packs", "cta": "Buy", "image_prompt": "a hiker"}')
        result = creative_mod.generate_creative(
            "Light packs", PERSONA, domain_category="retail", active_channels=["bluesky"], brand=BrandKit(forbidden_words=["cheap"]),
        )
        assert result.headline == "" and result.cta == "Buy"

    def test_layout_failure_ships_the_bare_picture(self, wired, monkeypatch):
        wired('{"copy": "Trail-ready in minutes.", "headline": "Half the weight", "cta": "Shop", "image_prompt": "a"}')

        def boom(*a, **k):
            raise OSError("no font")

        monkeypatch.setattr(creative_mod, "compose_ad", boom)
        result = creative_mod.generate_creative("Light packs", PERSONA, domain_category="retail", active_channels=["bluesky"])
        assert result.image_bytes == _picture()


class TestOpenAIImageSwitch:
    @pytest.fixture(autouse=True)
    def env(self, monkeypatch):
        for key in ("PAID_IMAGE_API_KEY", "PAID_LLM_API_KEY", "FORCE_FREE_TIER", "HF_TOKEN", "GEMINI_API_KEY", "OPENAI_IMAGE_GEN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def _chain(self):
        from src.providers import registry

        provider = registry.get_image_generator()
        return [type(p).__name__ for p in getattr(provider, "_providers", [provider])]

    @pytest.mark.parametrize("value", [None, "off", "true", "yes", ""])
    def test_off_unless_explicitly_on(self, monkeypatch, value):
        if value is not None:
            monkeypatch.setenv("OPENAI_IMAGE_GEN", value)
        assert "OpenAIImageProvider" not in self._chain()

    def test_on_puts_openai_first_with_pollinations_behind(self, monkeypatch):
        monkeypatch.setenv("OPENAI_IMAGE_GEN", "on")
        assert self._chain() == ["OpenAIImageProvider", "PollinationsImageProvider"]
        monkeypatch.delenv("OPENAI_API_KEY")
        assert self._chain() == ["PollinationsImageProvider"]

    def test_gpt_image_requests_never_send_response_format(self, monkeypatch):
        from src.providers.paid import openai_image

        sent = {}

        class Images:
            def generate(self, **kwargs):
                sent.update(kwargs)
                return type("R", (), {"data": [type("D", (), {"b64_json": base64.b64encode(b"png").decode()})()]})()

        provider = openai_image.OpenAIImageProvider(api_key="sk-test")
        monkeypatch.setattr(provider._client, "images", Images())
        assert provider.generate_image("x") == b"png" and "response_format" not in sent


class TestCloudflare:
    @pytest.fixture(autouse=True)
    def env(self, monkeypatch):
        from src.providers.free.cloudflare_image import CloudflareImageProvider

        monkeypatch.setattr(CloudflareImageProvider, "disabled_reason", None)
        monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct123")
        monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "cf-test")

    def test_runs_flux_and_decodes_the_image(self, monkeypatch):
        from src.providers.free import cloudflare_image

        sent = {}

        def post(url, headers, json, timeout):
            sent.update(url=url, headers=headers, json=json)
            return _Response(200, {"result": {"image": base64.b64encode(b"jpg").decode()}, "success": True})

        monkeypatch.setattr(cloudflare_image.requests, "post", post)
        assert cloudflare_image.CloudflareImageProvider().generate_image("a bike" * 600) == b"jpg"
        assert sent["url"] == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/@cf/black-forest-labs/flux-1-schnell"
        assert sent["headers"]["Authorization"] == "Bearer cf-test"
        assert len(sent["json"]["prompt"]) == 2048 and sent["json"]["steps"] == 8

    def test_bad_token_disables_it_but_a_spent_daily_allowance_does_not(self, monkeypatch):
        from src.providers.free import cloudflare_image

        calls = []
        monkeypatch.setattr(cloudflare_image.requests, "post", lambda *a, **k: calls.append(1) or _Response(429))
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cloudflare_image.CloudflareImageProvider().generate_image("x")
        assert len(calls) == 2  # retried: the allowance resets
        monkeypatch.setattr(cloudflare_image.requests, "post", lambda *a, **k: calls.append(1) or _Response(403))
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cloudflare_image.CloudflareImageProvider().generate_image("x")
        assert len(calls) == 3
        monkeypatch.setattr(cloudflare_image.CloudflareImageProvider, "disabled_reason", None)
        monkeypatch.setattr(cloudflare_image.requests, "post", lambda *a, **k: _Response(200, {"result": {}}))
        with pytest.raises(RuntimeError, match="no image"):
            cloudflare_image.CloudflareImageProvider().generate_image("x")

    def test_chain_order(self, monkeypatch):
        from src.providers import registry

        for key in ("PAID_IMAGE_API_KEY", "PAID_LLM_API_KEY", "FORCE_FREE_TIER", "OPENAI_IMAGE_GEN"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("HF_TOKEN", "hf")
        monkeypatch.setenv("GEMINI_API_KEY", "g")
        names = [type(p).__name__ for p in registry.get_image_generator()._providers]
        assert names == ["CloudflareImageProvider", "HuggingFaceImageProvider", "GeminiImageProvider", "PollinationsImageProvider"]
        monkeypatch.delenv("CLOUDFLARE_API_TOKEN")
        assert "CloudflareImageProvider" not in [type(p).__name__ for p in registry.get_image_generator()._providers]


class TestLayouts:
    def test_every_bandit_style_has_its_own_layout(self):
        from src.tools.ad_composer import LAYOUTS
        from src.tools.bandit import IMAGE_STYLES

        assert set(LAYOUTS) == set(IMAGE_STYLES)
        ads = {
            style: compose_ad(_picture(), "Your coffee, ready before you are", "Order ahead", style=style)
            for style in IMAGE_STYLES
        }
        assert len(set(ads.values())) == len(IMAGE_STYLES)  # all different
        for fmt in ("square", "banner"):
            for style in IMAGE_STYLES:
                assert _open(compose_ad(_picture(500, 900), "Café, listo ya", "Pide", style=style, fmt=fmt)).size == SIZES[fmt]

    def test_unknown_style_falls_back_to_lifestyle(self):
        assert compose_ad(_picture(), "Hi there", "Go", style="nope") == compose_ad(_picture(), "Hi there", "Go", style="lifestyle_aspirational")

    def test_layouts_cope_with_missing_parts(self):
        from src.tools.bandit import IMAGE_STYLES

        for style in IMAGE_STYLES:
            for headline, cta in (("Only a headline", ""), ("", "Only a button"), ("word " * 40, "a long call to action label")):
                assert _open(compose_ad(_picture(), headline, cta, style=style)).size == (1080, 1080)

    def test_minimalist_keeps_the_picture_free_of_any_fade(self):
        ad = _open(compose_ad(_picture(color=(40, 120, 200)), "Calm", "Go", style="minimalist")).convert("RGB")
        r, g, b = ad.getpixel((540, 1060))  # bottom of the picture: untouched blue
        assert abs(r - 40) < 12 and abs(g - 120) < 12 and abs(b - 200) < 12
        assert ad.getpixel((1060, 20))[0] > 230  # paper band at the top

    def test_urgency_band_is_the_brand_colour(self):
        ad = _open(compose_ad(_picture(), "Go now", "Shop", brand_color="#00aa55", style="urgency_scarcity")).convert("RGB")
        r, g, b = ad.getpixel((1060, 1070))
        assert g > 140 and r < 60

    def test_lines_are_balanced_without_a_lone_last_word(self):
        from PIL import ImageDraw

        from src.tools.ad_composer import _fit

        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        text = _fit(draw, "Your coffee, ready before you are", 960, 108, 60, weight="Black")
        assert len(text.lines) > 1 and len(text.lines[-1].split()) > 1

    def test_creative_uses_the_arms_style(self, monkeypatch, fake_llm):
        seen = {}
        monkeypatch.setattr(creative_mod, "compose_ad", lambda *a, **k: seen.update(k) or b"ad")
        monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: fake_llm('{"copy": "Fresh.", "headline": "H", "cta": "C", "image_prompt": "p"}'))

        class Images:
            supports_outpainting = False

            def generate_image(self, prompt):
                return _picture()

        monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Images())
        creative_mod.generate_creative(
            "Coffee", PERSONA, domain_category="food_beverage", active_channels=["bluesky"], arm=(9, "humor_meme", "humorous"),
        )
        assert seen["style"] == "humor_meme"
