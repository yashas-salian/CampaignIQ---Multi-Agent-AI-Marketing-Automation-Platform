"""The fine-tuned classifier's prompt and output parsing, shared by training,
evaluation and the production provider so they can never drift apart.

train_lora.ipynb carries a copy (Colab can't import this repo); keep it in sync.
The student answers with the bare label, not JSON: fewer tokens to generate and
nothing to mis-format.
"""
from src.capabilities.idea_intake import DOMAIN_CATEGORIES

SYSTEM = "You classify ad-campaign ideas into one product category. Answer with the category name only."


def build_messages(idea: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Categories: {', '.join(DOMAIN_CATEGORIES)}\nIdea: {idea.strip()}\nCategory:"},
    ]


def parse_label(text: str) -> str | None:
    """First valid category in the model's reply, or None if it produced none."""
    cleaned = text.strip().strip('"\'`.').lower()
    if cleaned in DOMAIN_CATEGORIES:
        return cleaned
    for category in DOMAIN_CATEGORIES:
        if category in cleaned:
            return category
    return None
