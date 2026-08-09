import json

from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.providers.registry import get_image_generator, get_llm


class Creative(BaseModel):
    copy_text: str
    image_prompt: str
    image_bytes: bytes


def generate_creative(idea: str, persona: Persona, *, user_id: str | None = None) -> Creative:
    response = get_llm(user_id).generate(
        f"Ad campaign idea: \"{idea}\"\n"
        f"Target persona: {persona.model_dump()}\n\n"
        "Write ad creative for this persona. Respond with ONLY a JSON object, no prose, "
        'with exactly two keys: "copy" (a short ad copy, 2-3 sentences, tone matching the '
        'persona\'s messaging_angle) and "image_prompt" (a vivid, concrete visual description '
        "suitable for an image generation model, matching the copy)." ,
        system="You are an ad creative director. You output only valid JSON, never prose or markdown fences.",
    )
    payload = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(payload)

    image_bytes = get_image_generator(user_id).generate_image(parsed["image_prompt"])
    return Creative(copy_text=parsed["copy"], image_prompt=parsed["image_prompt"], image_bytes=image_bytes)
