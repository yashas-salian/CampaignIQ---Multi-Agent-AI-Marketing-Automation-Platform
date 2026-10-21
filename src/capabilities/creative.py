import base64

from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.capabilities.brand import BrandKit
from src.capabilities.guardrails import GuardrailResult, check_creative, rewrite_directive
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_image_generator, get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence
from src.tools.bandit import select_arm_for_campaign
from src.tools.image_compositing import overlay_template


class Creative(BaseModel):
    copy_text: str
    image_prompt: str
    image_bytes: bytes
    image_style: str
    copy_tone: str
    arm_index: int
    guardrails: GuardrailResult = GuardrailResult()


# Extra copy attempts when brand-safety checks block a draft (see guardrails.py).
MAX_GUARDRAIL_REWRITES = 2


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
) -> Creative:
    arm_index, image_style, copy_tone = arm or select_arm_for_campaign(
        persona.age_bracket, persona.income_tier, domain_category, active_channels
    )
    directive_text = (
        f"\nRevision guidance from the previous round's performance:\n{fence(revision_directive, 'revision_directive')}\n"
        if revision_directive
        else ""
    )
    safety_text = ""
    best: tuple[dict, GuardrailResult] | None = None
    for _ in range(1 + MAX_GUARDRAIL_REWRITES):
        prompt, system = PROMPTS["creative.generate"].render(
            idea=fence(idea, "user_idea"),
            persona=fence(persona.model_dump(), "persona"),
            brand=brand.prompt_section() if brand else "",
            image_style=image_style,
            copy_tone=copy_tone,
            directive=directive_text,
            safety=safety_text,
            language=language_name(target_language),
        )
        parsed = generate_json(get_llm(user_id), prompt, system=system)
        checks = check_creative(
            str(parsed.get("copy", "")), domain_category=domain_category, channels=active_channels,
            cta_url=cta_url, banned_terms=[*banned_terms, *(brand.forbidden_words if brand else [])],
        )
        if best is None or len(checks.blocked) < len(best[1].blocked):
            best = (parsed, checks)
        if checks.ok:
            break
        safety_text = f"\n{rewrite_directive(checks)}\n"
    parsed, checks = best

    image_provider = get_image_generator(user_id)
    template_bytes = None
    if use_image_template and user_id:
        from src.db.supabase_client import get_template

        template = get_template(user_id, "image")
        if template and template.get("image_base64"):
            template_bytes = base64.b64decode(template["image_base64"])

    if template_bytes is not None and image_provider.supports_outpainting:
        # Pro feature (paid/BYOK only): the template is the fixed foundation --
        # generate new content around it, preserving its pixels exactly.
        image_bytes = image_provider.outpaint(template_bytes, parsed["image_prompt"])
    else:
        # Free tier (or no template): generate normally. If a template was
        # requested but this provider can't outpaint, composite it on top as
        # a corner overlay instead of silently ignoring the user's request.
        image_bytes = image_provider.generate_image(parsed["image_prompt"])
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
    )
