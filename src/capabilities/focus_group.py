"""Synthetic focus group: before Gate 2, the campaign's personas react to the
draft ad (click / scroll past / object, with a one-line reason), so the
approver sees an audience verdict next to the copy. One LLM call for the
whole panel; the result is advice, never a gate."""
from typing import Literal

from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence

Reaction = Literal["click", "scroll", "object"]
_REACTIONS = ("click", "scroll", "object")


class PersonaReaction(BaseModel):
    name: str
    archetype: str = "general"
    gender: str = "unspecified"
    reaction: Reaction
    likelihood: int
    quote: str


class FocusGroupResult(BaseModel):
    reactions: list[PersonaReaction]
    verdict: dict[str, int]  # how many would click / scroll past / object
    average_likelihood: int


def run_focus_group(
    creative: Creative, personas: list[Persona], *, user_id: str | None = None, target_language: str = "en"
) -> FocusGroupResult:
    panel = "\n".join(f"- {p.name}: {p.demographics} | {p.psychographics} | cares about: {p.messaging_angle}" for p in personas)
    prompt, system = PROMPTS["focus_group.react"].render(
        copy=fence(creative.copy_text, "ad_copy"),
        image_prompt=fence(creative.image_prompt, "image_prompt"),
        panel=fence(panel, "personas"),
        language=language_name(target_language),
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)
    answers = parsed if isinstance(parsed, list) else parsed.get("reactions", [])

    reactions: list[PersonaReaction] = []
    for i, persona in enumerate(personas):
        # Match by position (the prompt asks for the same order); the model's
        # free-text fields are coerced so one odd answer can't fail the panel.
        raw = answers[i] if i < len(answers) and isinstance(answers[i], dict) else {}
        reaction = str(raw.get("reaction", "")).strip().lower()
        try:
            likelihood = max(0, min(100, int(raw.get("likelihood", 0))))
        except (TypeError, ValueError):
            likelihood = 0
        reactions.append(
            PersonaReaction(
                name=persona.name,
                archetype=persona.archetype,
                gender=persona.gender,
                reaction=reaction if reaction in _REACTIONS else ("click" if likelihood >= 60 else "scroll"),
                likelihood=likelihood,
                quote=str(raw.get("quote", "")).strip()[:240],
            )
        )
    verdict = {r: sum(1 for x in reactions if x.reaction == r) for r in _REACTIONS}
    average = round(sum(r.likelihood for r in reactions) / len(reactions)) if reactions else 0
    return FocusGroupResult(reactions=reactions, verdict=verdict, average_likelihood=average)
