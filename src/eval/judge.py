from pydantic import BaseModel

from src.capabilities.audience import Persona
from src.llm_json import generate_json
from src.prompts import PROMPTS
from src.providers.registry import get_judge_llm


class PersonaJudgement(BaseModel):
    score: int
    reasoning: str


def judge_personas(idea: str, personas: list[Persona], *, user_id: str | None = None) -> PersonaJudgement:
    personas_text = "\n".join(
        f"- {p.name}: {p.demographics} | {p.psychographics} | channel_fit={p.channel_fit} | angle={p.messaging_angle}"
        for p in personas
    )
    prompt, system = PROMPTS["eval.judge_personas"].render(idea=idea, personas=personas_text)
    parsed = generate_json(get_judge_llm(user_id), prompt, system=system)
    return PersonaJudgement(**parsed)


def feasibility_in_range(score: int, expected_min: int, expected_max: int) -> bool:
    return expected_min <= score <= expected_max
