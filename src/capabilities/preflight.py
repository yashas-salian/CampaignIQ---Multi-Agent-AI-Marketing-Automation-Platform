from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence

PREFLIGHT_PASS_THRESHOLD = 50


class PreflightResult(BaseModel):
    predicted_engagement: int
    passed: bool
    panel_feedback: str


def score_preflight(
    creative: Creative, personas: list[Persona], *, user_id: str | None = None, target_language: str = "en"
) -> PreflightResult:
    panel_text = "\n".join(f"- {p.name}: {p.demographics} | {p.psychographics}" for p in personas)
    prompt, system = PROMPTS["preflight.panel"].render(
        copy=fence(creative.copy_text, "ad_copy"),
        image_prompt=fence(creative.image_prompt, "image_prompt"),
        panel=fence(panel_text, "personas"),
        language=language_name(target_language),
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)
    predicted_engagement = parsed["predicted_engagement"]
    return PreflightResult(
        predicted_engagement=predicted_engagement,
        passed=predicted_engagement >= PREFLIGHT_PASS_THRESHOLD,
        panel_feedback=parsed["panel_feedback"],
    )
