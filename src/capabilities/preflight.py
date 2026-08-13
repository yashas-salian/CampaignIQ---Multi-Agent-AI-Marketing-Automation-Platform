from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.llm_json import generate_json
from src.providers.registry import get_llm

PREFLIGHT_PASS_THRESHOLD = 50


class PreflightResult(BaseModel):
    predicted_engagement: int
    passed: bool
    panel_feedback: str


def score_preflight(creative: Creative, personas: list[Persona], *, user_id: str | None = None) -> PreflightResult:
    panel_text = "\n".join(f"- {p.name}: {p.demographics} | {p.psychographics}" for p in personas)
    parsed = generate_json(
        get_llm(user_id),
        f'Ad copy: "{creative.copy_text}"\n'
        f'Image description: "{creative.image_prompt}"\n\n'
        f"You are simulating how this panel of target personas would honestly react:\n{panel_text}\n\n"
        "Estimate an overall predicted engagement score (0-100, where 100 = extremely likely to "
        "engage/click/share, 0 = would ignore or dislike it). Respond with ONLY a JSON object, no "
        'prose, with exactly two keys: "predicted_engagement" (integer 0-100) and "panel_feedback" '
        "(one or two sentences summarizing the panel's honest reaction).",
        system=(
            "You are a panel of skeptical target-audience consumers giving honest, critical ad "
            "feedback. You output only valid JSON, never prose or markdown fences."
        ),
    )
    predicted_engagement = parsed["predicted_engagement"]
    return PreflightResult(
        predicted_engagement=predicted_engagement,
        passed=predicted_engagement >= PREFLIGHT_PASS_THRESHOLD,
        panel_feedback=parsed["panel_feedback"],
    )
