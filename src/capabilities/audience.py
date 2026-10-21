from typing import Literal

from pydantic import BaseModel

from src.capabilities.feasibility import FeasibilityResult
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence

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
    prompt, system = PROMPTS["audience.personas"].render(
        idea=fence(idea, "user_idea"),
        rationale=fence(feasibility.rationale, "feasibility_rationale"),
        n=n,
        language=language_name(target_language),
        age_brackets=list(_AGE_BRACKETS),
        income_tiers=list(_INCOME_TIERS),
    )
    personas_raw = generate_json(get_llm(user_id), prompt, system=system)
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
