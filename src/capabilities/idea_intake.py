from typing import Literal, get_args

from pydantic import BaseModel

from src.llm_json import generate_json
from src.providers.free.groq_llm import GroqLLMProvider
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


def normalize_idea(raw_idea: str, *, user_id: str | None = None, use_local: bool = True) -> NormalizedIdea:
    """Classify the idea's product domain.

    Free tier: the M7 fine-tuned local model decides (no Groq call), falling
    back to the LLM if it's unavailable or unsure. Paid/BYOK users keep their
    paid LLM. use_local=False forces the LLM -- the M7 dataset builder and the
    evaluation's teacher row need the real teacher, never the student.
    """
    idea = raw_idea.strip()
    llm = get_llm(user_id)
    if use_local and isinstance(llm, GroqLLMProvider):
        # Lazy import: the local classifier imports this module for DOMAIN_CATEGORIES.
        from src.providers.free.local_domain_classifier import classify_domain

        label = classify_domain(idea)
        if label is not None:
            return NormalizedIdea(idea=idea, domain_category=label)
    parsed = generate_json(
        llm,
        f'Campaign idea: "{idea}"\n\n'
        f"Classify this idea into exactly one of these domain/category tags: {list(DOMAIN_CATEGORIES)}. "
        'Respond with ONLY a JSON object, no prose, with exactly one key: "domain_category".',
        system="You are a strict classifier. You output only valid JSON, never prose or markdown fences.",
    )
    return NormalizedIdea(idea=idea, domain_category=parsed["domain_category"])
