from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.llm_json import generate_json
from src.providers.registry import get_judge_llm


class PersonaJudgement(BaseModel):
    score: int
    reasoning: str


def judge_personas(idea: str, personas: list[Persona], *, user_id: str | None = None) -> PersonaJudgement:
    personas_text = "\n".join(
        f"- {p.name}: {p.demographics} | {p.psychographics} | channel_fit={p.channel_fit} | angle={p.messaging_angle}"
        for p in personas
    )
    parsed = generate_json(
        get_judge_llm(user_id),
        f'Campaign idea: "{idea}"\n\nGenerated personas:\n{personas_text}\n\n'
        "Judge these personas on relevance to the idea, specificity (not generic), and actionability "
        "for an ad campaign. Respond with ONLY a JSON object, no prose, with exactly two keys: "
        '"score" (integer 1-5, 5=excellent) and "reasoning" (one sentence).',
        system=(
            "You are a strict, consistent marketing quality judge. "
            "You output only valid JSON, never prose or markdown fences."
        ),
    )
    return PersonaJudgement(**parsed)


def feasibility_in_range(score: int, expected_min: int, expected_max: int) -> bool:
    return expected_min <= score <= expected_max
