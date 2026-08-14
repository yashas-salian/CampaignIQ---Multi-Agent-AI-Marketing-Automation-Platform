import numpy as np

from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.db.supabase_client import get_client

IMAGE_STYLES = ["minimalist", "testimonial_social_proof", "humor_meme", "urgency_scarcity", "lifestyle_aspirational"]
COPY_TONES = ["direct_factual", "urgency_scarcity", "humorous", "aspirational_emotional"]
ARMS = [(style, tone) for style in IMAGE_STYLES for tone in COPY_TONES]  # 20 arms, index 0-19

AGE_BRACKETS = ["18-24", "25-34", "35-44", "45-54", "55+"]
INCOME_TIERS = ["low", "mid", "high"]
CHANNELS = ["bluesky", "reddit", "email"]

# age_bracket(5) + income_tier(3) + channel(3) + domain_category(12) + bias(1)
CONTEXT_DIM = len(AGE_BRACKETS) + len(INCOME_TIERS) + len(CHANNELS) + len(DOMAIN_CATEGORIES) + 1

ALPHA = 0.5  # LinUCB exploration weight, reward-scale-appropriate (rewards are in [0, 1])


def _one_hot(value: str, categories: list[str]) -> list[float]:
    return [1.0 if value == c else 0.0 for c in categories]


def build_context_vector(age_bracket: str, income_tier: str, channel: str, domain_category: str) -> np.ndarray:
    vector = (
        _one_hot(age_bracket, AGE_BRACKETS)
        + _one_hot(income_tier, INCOME_TIERS)
        + _one_hot(channel, CHANNELS)
        + _one_hot(domain_category, DOMAIN_CATEGORIES)
        + [1.0]  # bias term
    )
    # L2-normalized: raw one-hot concatenation has ||x|| = sqrt(5) (4 active
    # groups + bias), which would make an untried arm's exploration bonus
    # (alpha * sqrt(x^T A^-1 x), = alpha * ||x|| at the identity prior)
    # permanently exceed any reward-scale (0-1) exploitation term no matter
    # how much data accumulates -- normalizing to unit length ties the
    # exploration bonus to the same [0, 1]-ish scale as the reward itself.
    array = np.array(vector, dtype=float)
    return array / np.linalg.norm(array)


def _seed_arms_if_empty() -> None:
    existing = get_client().table("bandit_arms").select("arm_index").limit(1).execute()
    if existing.data:
        return
    identity = np.eye(CONTEXT_DIM).tolist()
    zeros = [0.0] * CONTEXT_DIM
    rows = [
        {"arm_index": i, "image_style": style, "copy_tone": tone, "a_matrix": identity, "b_vector": zeros}
        for i, (style, tone) in enumerate(ARMS)
    ]
    get_client().table("bandit_arms").upsert(rows, on_conflict="arm_index").execute()


def _get_all_arms() -> list[dict]:
    _seed_arms_if_empty()
    result = get_client().table("bandit_arms").select("*").order("arm_index").execute()
    return result.data


def _ucb_score(arm: dict, context: np.ndarray) -> float:
    a_matrix = np.array(arm["a_matrix"])
    b_vector = np.array(arm["b_vector"])
    a_inv = np.linalg.inv(a_matrix)
    theta = a_inv @ b_vector
    return float(theta @ context + ALPHA * np.sqrt(context @ a_inv @ context))


def select_arm_for_campaign(
    age_bracket: str, income_tier: str, domain_category: str, active_channels: list[str]
) -> tuple[int, str, str]:
    """Pick the arm (image_style, copy_tone) for a round's single creative.

    One creative serves every active channel, so selection scores each active
    channel's context separately and picks the arm with the highest summed
    UCB score across them -- this is what lets "channel" stay part of the
    fixed context vector even though there's no per-channel creative.
    """
    arms = _get_all_arms()
    contexts = [build_context_vector(age_bracket, income_tier, channel, domain_category) for channel in active_channels]

    best_index, best_score = 0, float("-inf")
    for arm in arms:
        total_score = sum(_ucb_score(arm, context) for context in contexts)
        if total_score > best_score:
            best_index, best_score = arm["arm_index"], total_score

    image_style, copy_tone = ARMS[best_index]
    return best_index, image_style, copy_tone


def update_arm(arm_index: int, context: np.ndarray, reward: float) -> None:
    result = get_client().table("bandit_arms").select("*").eq("arm_index", arm_index).single().execute()
    arm = result.data
    a_matrix = np.array(arm["a_matrix"])
    b_vector = np.array(arm["b_vector"])

    a_matrix = a_matrix + np.outer(context, context)
    b_vector = b_vector + reward * context

    get_client().table("bandit_arms").update(
        {
            "a_matrix": a_matrix.tolist(),
            "b_vector": b_vector.tolist(),
            "pulls": arm["pulls"] + 1,
            "total_reward": float(arm["total_reward"]) + reward,
        }
    ).eq("arm_index", arm_index).execute()
