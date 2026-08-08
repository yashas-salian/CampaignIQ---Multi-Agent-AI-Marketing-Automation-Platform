import json

from pydantic import BaseModel

from src.capabilities.feasibility import FeasibilityResult
from src.providers.registry import get_llm


class Persona(BaseModel):
    name: str
    demographics: str
    psychographics: str
    channel_fit: str
    messaging_angle: str


def generate_personas(idea: str, feasibility: FeasibilityResult, *, n: int = 3) -> list[Persona]:
    response = get_llm().generate(
        f"Ad campaign idea: \"{idea}\"\n"
        f"Feasibility rationale: {feasibility.rationale}\n\n"
        f"Generate exactly {n} distinct ideal-customer-profile personas for this campaign. "
        "Respond with ONLY a JSON array, no prose, where each element has exactly these keys: "
        '"name", "demographics", "psychographics", "channel_fit", "messaging_angle".',
        system="You are an audience research strategist. You output only valid JSON, never prose or markdown fences.",
    )
    payload = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    personas_raw = json.loads(payload)
    return [Persona(**p) for p in personas_raw]
