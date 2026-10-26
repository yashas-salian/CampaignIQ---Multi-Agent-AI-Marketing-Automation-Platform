import base64
import logging

from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.capabilities.brand import BrandKit, brand_logo
from src.capabilities.guardrails import GuardrailResult, check_creative, rewrite_directive
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_image_generator, get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence
from src.tools.bandit import select_arm_for_campaign
from src.tools.ad_composer import compose_ad
from src.tools.ad_templates import Slots, compose_product_ad, family_menu, resolve
from src.tools.image_compositing import overlay_template

logger = logging.getLogger("capabilities.creative")


class Creative(BaseModel):
    copy_text: str
    image_prompt: str
    # The finished ad: the generated picture with the headline and CTA set on it.
    image_bytes: bytes
    image_style: str
    copy_tone: str
    arm_index: int
    guardrails: GuardrailResult = GuardrailResult()
    # Why the bandit picked this arm (bandit.explain_choice); shown as "Why this ad?".
    arm_explain: dict | None = None
    headline: str = ""
    cta: str = ""
    # Product-first ads (src/tools/ad_templates.py): the layout used and the
    # extra words on it, kept so Gate 2 can redraw the same ad.
    template: str = ""
    ad_slots: dict | None = None
    # The painted background of a scene template, kept so the ad can be
    # redrawn with new words (crash-test revision) without painting again.
    scene_bytes: bytes | None = None


# Extra copy attempts when brand-safety checks block a draft (see guardrails.py).
MAX_GUARDRAIL_REWRITES = 2

# Appended to every image prompt: weaker free models drift into illustration
# and painted-on gibberish text without it.
AD_VISUAL_SUFFIX = ", professional advertising photography, high detail, no text, no letters, no watermark"
# Appended to a template's background: the real product is set into it
# afterwards, so the model must leave the spot empty and draw no product.
SCENE_SUFFIX = (
    ", professional advertising background photography, empty space in the centre for a product to be placed later, "
    "no product, no packaging, no bottles, no text, no letters, no logos, no watermark"
)

# The prompt's visual instructions and JSON keys: product-first ads (the
# campaign's photo set into a template) or, without a photo (the Tools page),
# a picture the image model paints with the product as its hero.
_PRODUCT_VISUAL = (
    "The ad is built around the campaign's real product photo, set into one of these layout templates "
    "for the {style} style (pick the one that suits this product and situation best; people appear only "
    "in templates made for them):\n{menu}\n"
)
_PRODUCT_KEYS = (
    '"template" (the chosen template id from the list), '
    '"slots" (an object with the extra on-image words in {language}, every value short and taken only from the idea: '
    '"eyebrow" (2-4 word label, e.g. the product type), "big_word" (one striking word), '
    '"benefits" (up to 3 benefits of at most 4 words each, only ones the idea states), '
    '"steps" (up to 3 how-it-works steps of at most 5 words, only if the idea describes how it works), '
    '"stat" (a number or price exactly as written in the idea, else empty), '
    '"badge" (an offer exactly as stated in the idea, else "New")) and '
    '"image_prompt" (always in English: only for templates that paint a background, describe that background '
    "as a professional advertising photograph with the centre left empty for the product, matching the "
    "product's colours and world; never the product itself, never text, letters or logos; for other templates "
    'one short line describing the mood)'
)
_PICTURE_VISUAL = ""
_PICTURE_KEYS = (
    '"image_prompt" (the ad\'s visual for an image generation model, always written in English regardless '
    "of the copy's language, since image generation models are English-prompt-optimized: a professional "
    "advertising photograph with the product itself as the hero and one clear focal subject, people only if "
    "the product needs them to make sense, clean uncluttered background, commercial lighting, and the bottom "
    "third of the frame kept simple and calm because the headline is set there later; never ask for any text, "
    "letters, signs, logos or watermarks in the image)"
)


def write_copy(
    idea: str,
    persona: Persona,
    *,
    domain_category: str,
    active_channels: list[str],
    image_style: str,
    copy_tone: str,
    user_id: str | None = None,
    revision_directive: str | None = None,
    target_language: str = "en",
    cta_url: str | None = None,
    banned_terms: tuple[str, ...] | list[str] = (),
    brand: BrandKit | None = None,
    playbook: str = "",
    memory: str = "",
    product_cutout: bytes | None = None,
    tagline: str = "",
    template: str | None = None,
) -> tuple[dict, GuardrailResult, list[str]]:
    """The words of an ad (copy, headline, CTA, visual brief) for an arm, rewritten
    until the guardrails pass (or the best attempt). No image is made here, so it
    can be evaluated without spending image-model calls. Returns (parsed, checks,
    forbidden words)."""
    directive_text = (
        f"\nRevision guidance from the previous round's performance:\n{fence(revision_directive, 'revision_directive')}\n"
        if revision_directive
        else ""
    )
    forbidden = [*banned_terms, *(brand.forbidden_words if brand else [])]
    safety_text = ""
    best: tuple[dict, GuardrailResult] | None = None
    for _ in range(1 + MAX_GUARDRAIL_REWRITES):
        prompt, system = PROMPTS["creative.generate"].render(
            idea=fence(idea, "user_idea"),
            persona=fence(persona.model_dump(), "persona"),
            brand=brand.prompt_section() if brand else "",
            playbook=playbook,
            memory=memory,
            image_style=image_style,
            copy_tone=copy_tone,
            directive=directive_text,
            safety=safety_text,
            language=language_name(target_language),
            tagline=f"Product tagline (set on the ad as written):\n{fence(tagline, 'tagline')}\n" if tagline else "",
            visual=_PRODUCT_VISUAL.format(style=image_style, menu=family_menu(image_style, only=template)) if product_cutout else _PICTURE_VISUAL,
            keys=(_PRODUCT_KEYS.format(language=language_name(target_language)) if product_cutout else _PICTURE_KEYS) + ".",
        )
        parsed = generate_json(get_llm(user_id), prompt, system=system)
        checks = check_creative(
            str(parsed.get("copy", "")), domain_category=domain_category, channels=active_channels,
            cta_url=cta_url, banned_terms=forbidden, language=target_language,
        )
        if best is None or len(checks.blocked) < len(best[1].blocked):
            best = (parsed, checks)
        if checks.ok:
            break
        safety_text = f"\n{rewrite_directive(checks)}\n"
    parsed, checks = best
    return parsed, checks, forbidden


def generate_creative(
    idea: str,
    persona: Persona,
    *,
    domain_category: str,
    active_channels: list[str],
    user_id: str | None = None,
    use_image_template: bool = False,
    revision_directive: str | None = None,
    target_language: str = "en",
    cta_url: str | None = None,
    banned_terms: tuple[str, ...] | list[str] = (),
    brand: BrandKit | None = None,
    arm: tuple[int, str, str] | None = None,
    playbook: str = "",
    memory: str = "",
    product_cutout: bytes | None = None,
    tagline: str = "",
    template: str | None = None,
) -> Creative:
    arm_index, image_style, copy_tone = arm or select_arm_for_campaign(
        persona.age_bracket, persona.income_tier, domain_category, active_channels
    )
    parsed, checks, forbidden = write_copy(
        idea, persona, domain_category=domain_category, active_channels=active_channels, user_id=user_id,
        revision_directive=revision_directive, target_language=target_language, cta_url=cta_url, banned_terms=banned_terms,
        brand=brand, playbook=playbook, memory=memory, image_style=image_style, copy_tone=copy_tone,
        product_cutout=product_cutout, tagline=tagline, template=template,
    )
    headline = _clean_line(parsed.get("headline"), forbidden)
    cta = _clean_line(parsed.get("cta"), forbidden)

    image_provider = get_image_generator(user_id)
    if product_cutout:
        return _product_creative(
            {**parsed, "template": template} if template else parsed, checks, product_cutout, image_provider,
            headline=headline, cta=cta, tagline=_clean_line(tagline, forbidden),
            forbidden=forbidden, brand=brand, image_style=image_style, copy_tone=copy_tone, arm_index=arm_index,
            arm_explain=_explain(persona, domain_category, active_channels, arm_index),
        )
    template_bytes = None
    if use_image_template and user_id:
        from src.db.supabase_client import get_template

        template = get_template(user_id, "image")
        if template and template.get("image_base64"):
            template_bytes = base64.b64decode(template["image_base64"])

    if template_bytes is not None and image_provider.supports_outpainting:
        # Pro feature (paid/BYOK only): the template is the fixed foundation --
        # generate new content around it, preserving its pixels exactly.
        # The template is the user's own layout, so no text is set on top.
        image_bytes = image_provider.outpaint(template_bytes, parsed["image_prompt"])
    else:
        # Free tier (or no template): generate normally. If a template was
        # requested but this provider can't outpaint, composite it on top as
        # a corner overlay instead of silently ignoring the user's request.
        image_bytes = _finish_ad(
            image_provider.generate_image(parsed["image_prompt"] + AD_VISUAL_SUFFIX), headline, cta, brand, image_style
        )
        if template_bytes is not None:
            image_bytes = overlay_template(image_bytes, template_bytes)

    return Creative(
        copy_text=parsed["copy"],
        image_prompt=parsed["image_prompt"],
        image_bytes=image_bytes,
        image_style=image_style,
        copy_tone=copy_tone,
        arm_index=arm_index,
        guardrails=checks,
        arm_explain=_explain(persona, domain_category, active_channels, arm_index),
        headline=headline,
        cta=cta,
    )


def _product_creative(
    parsed: dict, checks: GuardrailResult, product: bytes, image_provider, *, headline: str, cta: str, tagline: str,
    forbidden: list[str], brand: BrandKit | None, image_style: str, copy_tone: str, arm_index: int, arm_explain: dict | None,
) -> Creative:
    """The campaign's real product set into a template. Only templates with a
    painted background call the image model; if that call fails the template
    draws its own background, so a flaky image API never fails the round."""
    raw = parsed.get("slots") if isinstance(parsed.get("slots"), dict) else {}
    clean = {key: _clean_line(raw.get(key), forbidden) for key in ("eyebrow", "big_word", "stat", "badge")}
    for key in ("benefits", "steps"):
        items = raw.get(key) if isinstance(raw.get(key), list) else []
        clean[key] = [v for v in (_clean_line(x, forbidden) for x in items[:3]) if v]
    slots = Slots.from_dict({**clean, "headline": headline, "cta": cta, "tagline": tagline})
    template = resolve(str(parsed.get("template") or ""), image_style, slots)
    scene_prompt = str(parsed.get("image_prompt") or "").strip()
    scene = None
    if template.scene:
        scene_prompt = scene_prompt or template.scene
        try:
            scene = image_provider.generate_image(scene_prompt + SCENE_SUFFIX)
        except Exception as exc:
            logger.warning("background generation failed, the template draws its own: %s", exc)
    image_bytes = compose_product_ad(
        product, template.id, slots, brand_color=brand.brand_color if brand else None, logo_bytes=brand_logo(brand), scene_bytes=scene,
    )
    ad_slots = slots.as_dict()
    if template.scene:
        ad_slots["scene"] = scene_prompt
    return Creative(
        copy_text=parsed["copy"],
        image_prompt=_describe(template, scene_prompt if template.scene else "", slots),
        image_bytes=image_bytes,
        image_style=image_style,
        copy_tone=copy_tone,
        arm_index=arm_index,
        guardrails=checks,
        arm_explain=arm_explain,
        headline=headline,
        cta=cta,
        template=template.id,
        ad_slots=ad_slots,
        scene_bytes=scene,
    )


def _describe(template, scene: str, slots: Slots) -> str:
    """What the finished ad looks like, in words, for the audience panels and the novelty check."""
    look = template.suits.split(";")[-1].strip()
    parts = [f"The real product photo as the hero, laid out as {look}"]
    if scene:
        parts.append(f"set into {scene}")
    words = "; ".join(w for w in (slots.headline, slots.tagline, slots.cta) if w)
    if words:
        parts.append(f"with the words: {words}")
    return ", ".join(parts) + "."


def _clean_line(value, forbidden: list[str]) -> str:
    """One line of on-image text, or "" if missing or it uses a banned word
    (the copy's guardrail rewrites don't cover the headline and button)."""
    text = " ".join(str(value or "").split()).strip("\"'“”")
    if not text or any(term and term.lower() in text.lower() for term in forbidden):
        return ""
    return text


def _finish_ad(image_bytes: bytes, headline: str, cta: str, brand: BrandKit | None, image_style: str) -> bytes:
    # Each bandit image style has its own layout (ad_composer.LAYOUTS). Layout
    # is polish: if it fails, ship the bare picture rather than fail the round.
    try:
        return compose_ad(
            image_bytes, headline, cta, brand_color=brand.brand_color if brand else None, style=image_style,
            logo_bytes=brand_logo(brand),
        )
    except Exception as exc:
        logger.warning("ad layout failed, using the bare image: %s", exc)
        return image_bytes


def _explain(persona: Persona, domain_category: str, active_channels: list[str], arm_index: int) -> dict | None:
    # An explanation is nice to have: never let it fail a creative.
    try:
        from src.tools.bandit import explain_choice

        return explain_choice(persona.age_bracket, persona.income_tier, domain_category, active_channels, arm_index)
    except Exception:
        return None
