"""Product-first ads: the 34 templates, the product cut-out, and the creative
step that picks a template and fills its words. No image-model calls."""
import io
import json

import pytest
from PIL import Image, ImageDraw

from src.capabilities import creative as creative_mod
from src.capabilities.audience import Persona
from src.capabilities.brand import BrandKit
from src.tools import product_cutout
from src.tools.ad_templates import FAMILIES, M, SIZE, TEMPLATES, Slots, compose_product_ad, family_menu, render, resolve
from src.tools.bandit import IMAGE_STYLES

PERSONA = Persona(
    name="Maya", demographics="32, Denver", psychographics="weekend hiker", channel_fit="bluesky",
    messaging_angle="lighter packs", age_bracket="25-34", income_tier="mid",
)
FULL = Slots.from_dict({
    "headline": "Step into all-day comfort", "cta": "Shop now", "tagline": "Made to move with you", "eyebrow": "New arrival",
    "big_word": "Comfort", "benefits": ["Breathable canvas", "Cushioned sole", "Washable"],
    "steps": ["Pick your size", "Lace up", "Walk all day"], "stat": "₹2,499", "badge": "New",
})


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _bottle(width=300, height=600) -> bytes:
    """A product cut-out: an opaque bottle shape on transparency."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((width * 0.1, height * 0.25, width * 0.9, height - 1), radius=30, fill=(200, 140, 20, 255))
    d.rectangle((width * 0.35, 0, width * 0.65, height * 0.27), fill=(230, 230, 230, 255))
    return _png(image)


def _logo() -> bytes:
    return _png(Image.new("RGBA", (300, 100), (40, 39, 145, 255)))


def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def _overlap(a, b) -> int:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


class TestCatalogue:
    def test_at_least_thirty_templates_spread_over_every_bandit_style(self):
        assert len(TEMPLATES) >= 30
        assert set(FAMILIES) == set(IMAGE_STYLES)
        assert all(len(ids) >= 5 for ids in FAMILIES.values())

    def test_the_menu_lists_the_familys_templates_and_their_requirements(self):
        menu = family_menu("testimonial_social_proof")
        assert all(f"- {tid}:" in menu for tid in FAMILIES["testimonial_social_proof"])
        assert "only if you fill: stat" in menu

    def test_people_appear_only_in_templates_made_for_them(self):
        assert {t.id for t in TEMPLATES.values() if t.humans} == {"lifestyle_inset", "comic_scene"}

    @pytest.mark.parametrize(
        ("asked", "family", "slots", "expected"),
        [
            ("podium_showcase", "minimalist", Slots(), "podium_showcase"),
            ("nope", "minimalist", Slots(), "centered_hero"),
            ("starburst_badge", "minimalist", Slots(), "centered_hero"),  # another family's template
            ("big_number", "testimonial_social_proof", Slots(), "feature_callouts"),  # needs a stat; falls back
            ("big_number", "testimonial_social_proof", Slots(stat="50ml"), "big_number"),
            ("x", "unknown_style", Slots(), "centered_hero"),
        ],
    )
    def test_resolve_falls_back_to_the_familys_first_template(self, asked, family, slots, expected):
        assert resolve(asked, family, slots).id == expected


class TestTemplates:
    @pytest.mark.parametrize("tid", list(TEMPLATES))
    def test_renders_a_feed_square_with_everything_and_with_nothing(self, tid):
        for slots in (FULL, Slots(headline="Fresh every day"), Slots()):
            ad = _open(compose_product_ad(_bottle(), tid, slots, brand_color="#1f6feb", logo_bytes=_logo()))
            assert ad.format == "JPEG" and ad.size == (SIZE, SIZE)

    @pytest.mark.parametrize("tid", list(TEMPLATES))
    def test_words_stay_inside_the_frame_and_off_the_product(self, tid):
        ad = render(_bottle(), tid, FULL, brand_color="#1f6feb", logo_bytes=_logo())
        assert ad.product_box is not None
        for box in ad.text_boxes:
            assert box[0] >= M // 2 and box[1] >= M // 4 and box[2] <= SIZE - M // 2 and box[3] <= SIZE - M // 4, (tid, box)
        product_area = (ad.product_box[2] - ad.product_box[0]) * (ad.product_box[3] - ad.product_box[1])
        covered = sum(_overlap(box, ad.product_box) for box in ad.text_boxes)
        assert covered <= product_area * 0.08, tid  # at most a label's corner may touch it

    @pytest.mark.parametrize("tid", [t for t in TEMPLATES if t not in ("negative_space", "lifestyle_inset")])
    def test_the_product_is_the_hero(self, tid):
        ad = render(_bottle(), tid, FULL, brand_color="#1f6feb")
        height = ad.product_box[3] - ad.product_box[1]
        assert height >= SIZE * 0.3, (tid, height)

    def test_a_wide_product_fits_too(self):
        wide = _png(Image.new("RGBA", (900, 300), (20, 20, 20, 255)))
        for tid in TEMPLATES:
            ad = render(wide, tid, FULL)
            x0, y0, x1, y1 = ad.product_box
            assert x0 >= -40 and x1 <= SIZE + 40 and y1 <= SIZE, tid

    def test_seed_gives_a_different_drawn_variant(self):
        assert compose_product_ad(_bottle(), "centered_hero", FULL, seed=0) != compose_product_ad(_bottle(), "centered_hero", FULL, seed=1)

    def test_a_scene_template_uses_the_painted_background(self):
        scene = _png(Image.new("RGB", (800, 800), (0, 200, 0)))
        ad = _open(compose_product_ad(_bottle(), "scene_still_life", Slots(), scene_bytes=scene)).convert("RGB")
        assert ad.getpixel((20, SIZE // 2))[1] > 150  # green comes through at the edge

    def test_an_unreadable_scene_falls_back_to_a_drawn_background(self):
        assert _open(compose_product_ad(_bottle(), "flat_lay", FULL, scene_bytes=b"not an image")).size == (SIZE, SIZE)


class TestSlots:
    def test_words_the_fonts_cannot_set_are_left_off(self):
        slots = Slots.from_dict({"headline": "हर दिन ताज़ा", "cta": "Shop", "benefits": ["ताज़ा", "Fresh"]})
        assert slots.headline == "" and slots.cta == "Shop" and slots.benefits == ["Fresh"]

    def test_long_words_are_clipped_and_lists_capped(self):
        slots = Slots.from_dict({"headline": "word " * 40, "benefits": ["a", "b", "c", "d", "e"], "big_word": "two words"})
        assert len(slots.headline) <= 61 and len(slots.benefits) == 3 and slots.big_word == "two"


class TestCutout:
    def test_a_transparent_png_is_kept_and_trimmed(self):
        image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle((100, 50, 300, 350), fill=(255, 0, 0, 255))
        out = _open(product_cutout.cutout(_png(image)))
        assert out.mode == "RGBA" and out.size == (201, 301)

    def test_a_failed_background_removal_falls_back_to_a_card(self, monkeypatch):
        def boom(image):
            raise RuntimeError("model download failed")

        monkeypatch.setattr(product_cutout, "_remove_background", boom)
        photo = io.BytesIO()
        Image.new("RGB", (500, 300), (10, 120, 200)).save(photo, format="JPEG")
        out = _open(product_cutout.cutout(photo.getvalue()))
        assert out.mode == "RGBA" and out.width > 500 and out.getpixel((0, 0))[3] == 0  # rounded corner

    def test_a_patchy_mask_falls_back_to_a_card(self, monkeypatch):
        """A close-up that fills the frame has nothing to cut away: the model's
        mask comes back see-through, and the whole photo is shown instead."""
        def patchy(image):
            mask = Image.new("L", image.size, 150)  # unsure everywhere
            ImageDraw.Draw(mask).rectangle((0, 0, image.width // 2, image.height // 2), fill=255)
            return mask

        monkeypatch.setattr(product_cutout, "_mask", patchy)
        photo = io.BytesIO()
        Image.new("RGB", (400, 400), (90, 60, 30)).save(photo, format="JPEG")
        out = _open(product_cutout.cutout(photo.getvalue()))
        assert out.width > 400 and out.getpixel((out.width // 2, out.height // 2))[3] == 255

    def test_a_clean_mask_cuts_the_product_out(self, monkeypatch):
        def clean(image):
            mask = Image.new("L", image.size, 0)
            ImageDraw.Draw(mask).rectangle((100, 50, 299, 349), fill=255)
            return mask

        monkeypatch.setattr(product_cutout, "_mask", clean)
        photo = io.BytesIO()
        Image.new("RGB", (400, 400), (250, 250, 250)).save(photo, format="JPEG")
        out = _open(product_cutout.cutout(photo.getvalue()))
        assert out.size[0] in range(198, 203) and out.size[1] in range(298, 303)

    def test_long_words_never_lose_their_end_silently(self):
        from src.tools.ad_templates import fit

        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        block = fit(draw, "Hear every detail and block the noise all day long", "sans", 300, 40, 36, lines=1)
        assert block.lines[0].endswith("…")

    def test_no_clear_subject_falls_back_to_a_card(self, monkeypatch):
        monkeypatch.setattr(product_cutout, "_remove_background", lambda image: Image.new("RGBA", image.size, (0, 0, 0, 0)))
        photo = io.BytesIO()
        Image.new("RGB", (400, 400), (200, 200, 200)).save(photo, format="JPEG")
        assert _open(product_cutout.cutout(photo.getvalue())).width > 400


class TestProductCreative:
    @pytest.fixture
    def wired(self, monkeypatch, fake_llm):
        calls = []

        class Images:
            supports_outpainting = False

            def generate_image(self, prompt):
                calls.append(prompt)
                return _png(Image.new("RGB", (512, 512), (90, 160, 90)))

        monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Images())

        def use(reply: dict, style="minimalist"):
            llm = fake_llm(json.dumps(reply))
            monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)
            monkeypatch.setattr(creative_mod, "select_arm_for_campaign", lambda *a: (0, style, "direct_factual"))
            return llm, calls

        return use

    def _reply(self, **over):
        return {"copy": "Comfort for every step.", "headline": "All-day comfort", "cta": "Shop now", "template": "podium_showcase",
                "slots": {"benefits": ["Breathable", "Light"], "badge": "New"}, "image_prompt": "calm pastel mood", **over}

    def _run(self, **kw):
        return creative_mod.generate_creative(
            "Canvas sneakers", PERSONA, domain_category="retail", active_channels=["bluesky"],
            product_cutout=_bottle(), tagline="Made to move", **kw,
        )

    def test_a_drawn_template_makes_no_image_model_call(self, wired):
        llm, calls = wired(self._reply())
        result = self._run()
        assert calls == []
        assert result.template == "podium_showcase" and result.ad_slots["tagline"] == "Made to move"
        assert _open(result.image_bytes).size == (SIZE, SIZE)
        assert "real product photo" in result.image_prompt and "All-day comfort" in result.image_prompt

    def test_the_prompt_offers_the_familys_templates_and_forbids_invented_claims(self, wired):
        llm, _ = wired(self._reply())
        self._run()
        prompt = llm.prompts[0]
        assert "- podium_showcase:" in prompt and "- starburst_badge:" not in prompt
        assert "Made to move" in prompt and "customer names" in prompt and "PRODUCT is the hero" in prompt

    def test_a_scene_template_paints_only_the_background(self, wired):
        _, calls = wired(self._reply(template="scene_still_life", image_prompt="sunlit travertine stone"), style="lifestyle_aspirational")
        result = self._run()
        assert len(calls) == 1 and calls[0].startswith("sunlit travertine stone") and "no product" in calls[0]
        assert result.ad_slots["scene"] == "sunlit travertine stone"

    def test_a_failed_background_still_ships_the_ad(self, wired, monkeypatch):
        wired(self._reply(template="water_ripple"), style="lifestyle_aspirational")

        class Broken:
            supports_outpainting = False

            def generate_image(self, prompt):
                raise RuntimeError("quota")

        monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Broken())
        result = self._run()
        assert result.template == "water_ripple" and _open(result.image_bytes).size == (SIZE, SIZE)

    def test_an_unknown_template_falls_back_within_the_style(self, wired):
        wired(self._reply(template="made_up"))
        assert self._run().template == "centered_hero"

    def test_banned_words_are_dropped_from_every_slot(self, wired):
        wired(self._reply(slots={"benefits": ["Cheap thrills", "Light"], "eyebrow": "Cheap shoes"}))
        result = self._run(brand=BrandKit(forbidden_words=["cheap"]))
        assert result.ad_slots.get("benefits") == ["Light"] and "eyebrow" not in result.ad_slots

    def test_without_a_product_photo_the_picture_shows_the_product(self, wired):
        llm, calls = wired({"copy": "Comfort.", "headline": "All-day comfort", "cta": "Shop", "image_prompt": "a sneaker"})
        result = creative_mod.generate_creative("Canvas sneakers", PERSONA, domain_category="retail", active_channels=["bluesky"])
        assert result.template == "" and len(calls) == 1
        assert "product itself as the hero" in llm.prompts[0]


class TestFrontendMirror:
    def test_the_tools_page_lists_the_same_templates(self):
        import re
        from pathlib import Path

        ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "adTemplates.ts").read_text(encoding="utf-8")
        families = dict(re.findall(r"^\s+(\w+): \[([^\]]*)\]", ts, flags=re.M))
        assert {f: re.findall(r"'(\w+)'", ids) for f, ids in families.items()} == FAMILIES


class TestToolsImage:
    """The Tools page's ad image: the user's own product photo, set into a template."""

    @pytest.fixture
    def worker(self, monkeypatch):
        from src.scheduler import run_capability
        from src.capabilities import creative as creative_mod2
        from src.db import supabase_client

        seen = {}
        monkeypatch.setattr(supabase_client, "download_object", lambda bucket, path: seen.update(bucket=bucket, path=path) or _bottle())
        monkeypatch.setattr(run_capability, "personal_org", lambda user_id: "org-1")
        monkeypatch.setattr("src.capabilities.brand.brand_kit_for_org", lambda org: None)

        def fake_creative(idea, persona, **kw):
            seen.update(kw)
            return creative_mod2.Creative(copy_text="c", image_prompt="p", image_bytes=b"jpg", image_style="minimalist",
                                          copy_tone="direct_factual", arm_index=0, headline="h", template=kw.get("template") or "centered_hero")

        monkeypatch.setattr(creative_mod2, "generate_creative", fake_creative)
        return run_capability._run_image, seen

    def test_needs_a_photo(self, worker):
        run, _ = worker
        with pytest.raises(ValueError):
            run({"prompt": "Canvas sneakers"}, "u1")

    def test_refuses_someone_elses_photo(self, worker):
        run, _ = worker
        for path in ("u2/x.jpg", "u1/../u2/x.jpg"):
            with pytest.raises(PermissionError):
                run({"prompt": "Canvas sneakers", "product_image_path": path}, "u1")

    def test_builds_the_ad_around_the_photo_with_the_chosen_template(self, worker):
        run, seen = worker
        out = run({"prompt": "Canvas sneakers", "product_image_path": "u1/a.jpg", "tagline": "Made to move", "template": "starburst_badge"}, "u1")
        assert seen["bucket"] == "product-photos" and seen["path"] == "u1/a.jpg"
        assert seen["template"] == "starburst_badge" and seen["arm"][1] == "urgency_scarcity" and seen["tagline"] == "Made to move"
        assert seen["product_cutout"] and out["template"] == "starburst_badge" and out["mime"] == "image/jpeg"

    def test_an_unknown_template_means_best_fit(self, worker):
        run, seen = worker
        run({"prompt": "Canvas sneakers", "product_image_path": "u1/a.jpg", "template": "made_up"}, "u1")
        assert seen["template"] is None and seen["arm"] is None


def test_a_picked_template_is_the_only_one_offered_and_used(monkeypatch, fake_llm):
    llm = fake_llm(json.dumps({"copy": "c", "headline": "h", "cta": "Go", "template": "centered_hero", "slots": {}, "image_prompt": "m"}))
    monkeypatch.setattr(creative_mod, "get_llm", lambda user_id=None: llm)

    class Images:
        supports_outpainting = False

        def generate_image(self, prompt):
            raise AssertionError("a drawn template needs no image call")

    monkeypatch.setattr(creative_mod, "get_image_generator", lambda user_id=None: Images())
    result = creative_mod.generate_creative(
        "Canvas sneakers", PERSONA, domain_category="retail", active_channels=["bluesky"],
        product_cutout=_bottle(), template="type_sandwich", arm=(-1, "urgency_scarcity", "direct_factual"),
    )
    assert result.template == "type_sandwich"
    assert "- type_sandwich:" in llm.prompts[0] and "- starburst_badge:" not in llm.prompts[0]
