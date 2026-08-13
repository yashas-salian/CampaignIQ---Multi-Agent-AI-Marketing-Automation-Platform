from typing import Literal, get_args

from pydantic import BaseModel

from src.llm_json import generate_json
from src.providers.registry import get_llm

DomainCategory = Literal[
    "fitness_wellness",
    "b2b_saas",
    "ecommerce_retail",
    "food_beverage",
    "finance_fintech",
    "education",
    "consumer_electronics",
    "travel_hospitality",
    "real_estate",
    "healthcare",
    "entertainment_media",
    "other",
]

DOMAIN_CATEGORIES = get_args(DomainCategory)


class NormalizedIdea(BaseModel):
    idea: str
    domain_category: DomainCategory


def normalize_idea(raw_idea: str, *, user_id: str | None = None) -> NormalizedIdea:
    idea = raw_idea.strip()
    parsed = generate_json(
        get_llm(user_id),
        f'Campaign idea: "{idea}"\n\n'
        f"Classify this idea into exactly one of these domain/category tags: {list(DOMAIN_CATEGORIES)}. "
        'Respond with ONLY a JSON object, no prose, with exactly one key: "domain_category".',
        system="You are a strict classifier. You output only valid JSON, never prose or markdown fences.",
    )
    return NormalizedIdea(idea=idea, domain_category=parsed["domain_category"])
