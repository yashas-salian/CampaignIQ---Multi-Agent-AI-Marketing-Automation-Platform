import base64

from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.llm_json import generate_json
from src.providers.registry import get_image_generator, get_llm
from src.tools.image_compositing import overlay_template


class Creative(BaseModel):
    copy_text: str
    image_prompt: str
    image_bytes: bytes


def generate_creative(
    idea: str,
    persona: Persona,
    *,
    user_id: str | None = None,
    use_image_template: bool = False,
    revision_directive: str | None = None,
) -> Creative:
    directive_text = (
        f'\nRevision guidance from the previous round\'s performance: "{revision_directive}"\n' if revision_directive else ""
    )
    parsed = generate_json(
        get_llm(user_id),
        f"Ad campaign idea: \"{idea}\"\n"
        f"Target persona: {persona.model_dump()}\n"
        f"{directive_text}\n"
        "Write ad creative for this persona. Respond with ONLY a JSON object, no prose, "
        'with exactly two keys: "copy" (a short ad copy, 2-3 sentences, tone matching the '
        'persona\'s messaging_angle) and "image_prompt" (a vivid, concrete visual description '
        "suitable for an image generation model, matching the copy)." ,
        system="You are an ad creative director. You output only valid JSON, never prose or markdown fences.",
    )

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

    return Creative(copy_text=parsed["copy"], image_prompt=parsed["image_prompt"], image_bytes=image_bytes)
