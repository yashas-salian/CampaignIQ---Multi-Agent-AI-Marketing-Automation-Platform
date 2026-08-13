from pydantic import BaseModel

from src.capabilities.feasibility import FeasibilityResult
from src.llm_json import generate_json
from src.providers.registry import get_llm


class Persona(BaseModel):
    name: str
    demographics: str
    psychographics: str
    channel_fit: str
    messaging_angle: str


def _coerce_to_str(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def generate_personas(
    idea: str, feasibility: FeasibilityResult, *, n: int = 3, user_id: str | None = None
) -> list[Persona]:
    personas_raw = generate_json(
        get_llm(user_id),
        f"Ad campaign idea: \"{idea}\"\n"
        f"Feasibility rationale: {feasibility.rationale}\n\n"
        f"Generate exactly {n} distinct ideal-customer-profile personas for this campaign. "
        "Respond with ONLY a JSON array, no prose, where each element has exactly these keys, "
        "each a single plain string value (never a nested object or list): "
        '"name", "demographics", "psychographics", "channel_fit", "messaging_angle".',
        system="You are an audience research strategist. You output only valid JSON, never prose or markdown fences.",
    )
    return [
        Persona(
            name=_coerce_to_str(p["name"]),
            demographics=_coerce_to_str(p["demographics"]),
            psychographics=_coerce_to_str(p["psychographics"]),
            channel_fit=_coerce_to_str(p["channel_fit"]),
            messaging_angle=_coerce_to_str(p["messaging_angle"]),
        )
        for p in personas_raw
    ]
