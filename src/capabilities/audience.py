from typing import Literal

from pydantic import BaseModel

from src.capabilities.feasibility import FeasibilityResult
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm

AgeBracket = Literal["18-24", "25-34", "35-44", "45-54", "55+"]
IncomeTier = Literal["low", "mid", "high"]

_AGE_BRACKETS = ("18-24", "25-34", "35-44", "45-54", "55+")
_INCOME_TIERS = ("low", "mid", "high")


class Persona(BaseModel):
    name: str
    demographics: str
    psychographics: str
    channel_fit: str
    messaging_angle: str
    age_bracket: AgeBracket
    income_tier: IncomeTier


def _coerce_to_str(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _coerce_literal(value: object, allowed: tuple[str, ...], default: str) -> str:
    # Bandit context features must be exactly one of a fixed enum -- fall back
    # to a default bucket rather than crashing on an imprecise free-tier LLM value.
    text = _coerce_to_str(value).strip()
    return text if text in allowed else default


def generate_personas(
    idea: str,
    feasibility: FeasibilityResult,
    *,
    n: int = 3,
    user_id: str | None = None,
    target_language: str = "en",
) -> list[Persona]:
    personas_raw = generate_json(
        get_llm(user_id),
        f"Ad campaign idea: \"{idea}\"\n"
        f"Feasibility rationale: {feasibility.rationale}\n\n"
        f"Generate exactly {n} distinct ideal-customer-profile personas for this campaign. "
        "Respond with ONLY a JSON array, no prose, where each element has exactly these keys: "
        '"name", "demographics", "psychographics", "channel_fit", "messaging_angle" (each a single '
        "plain string value, never a nested object or list, written in "
        f"{language_name(target_language)} since these personas represent that target market), plus "
        f'"age_bracket" (exactly one of {list(_AGE_BRACKETS)}, always in English -- this is a fixed '
        f'category label, not display text) and "income_tier" (exactly one of {list(_INCOME_TIERS)}, same).',
        system="You are an audience research strategist. You output only valid JSON, never prose or markdown fences.",
    )
    return [
        Persona(
            name=_coerce_to_str(p["name"]),
            demographics=_coerce_to_str(p["demographics"]),
            psychographics=_coerce_to_str(p["psychographics"]),
            channel_fit=_coerce_to_str(p["channel_fit"]),
            messaging_angle=_coerce_to_str(p["messaging_angle"]),
            age_bracket=_coerce_literal(p.get("age_bracket"), _AGE_BRACKETS, "25-34"),
            income_tier=_coerce_literal(p.get("income_tier"), _INCOME_TIERS, "mid"),
        )
        for p in personas_raw
    ]
