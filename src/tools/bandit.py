import numpy as np

from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.db.supabase_client import get_client

IMAGE_STYLES = ["minimalist", "testimonial_social_proof", "humor_meme", "urgency_scarcity", "lifestyle_aspirational"]
COPY_TONES = ["direct_factual", "urgency_scarcity", "humorous", "aspirational_emotional"]
ARMS = [(style, tone) for style in IMAGE_STYLES for tone in COPY_TONES]  # 20 arms, index 0-19

AGE_BRACKETS = ["18-24", "25-34", "35-44", "45-54", "55+"]
INCOME_TIERS = ["low", "mid", "high"]
CHANNELS = ["bluesky", "reddit", "email"]
# Channels that share another's context slot: Mastodon is a short-form social
# feed like Bluesky, and a slot of its own would change CONTEXT_DIM (every
# stored arm matrix). Its rewards are still recorded per channel.
CONTEXT_ALIASES = {"mastodon": "bluesky"}

# age_bracket(5) + income_tier(3) + channel(3) + domain_category(12) + bias(1)
CONTEXT_DIM = len(AGE_BRACKETS) + len(INCOME_TIERS) + len(CHANNELS) + len(DOMAIN_CATEGORIES) + 1

ALPHA = 0.5  # LinUCB exploration weight, reward-scale-appropriate (rewards are in [0, 1])


def _one_hot(value: str, categories: list[str]) -> list[float]:
    return [1.0 if value == c else 0.0 for c in categories]


def build_context_vector(age_bracket: str, income_tier: str, channel: str, domain_category: str) -> np.ndarray:
    vector = (
        _one_hot(age_bracket, AGE_BRACKETS)
        + _one_hot(income_tier, INCOME_TIERS)
        + _one_hot(CONTEXT_ALIASES.get(channel, channel), CHANNELS)
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
    return select_arms_for_campaign(age_bracket, income_tier, domain_category, active_channels, k=1)[0]


def select_arms_for_campaign(
    age_bracket: str, income_tier: str, domain_category: str, active_channels: list[str], *, k: int = 2
) -> list[tuple[int, str, str]]:
    """The k best arms by summed UCB score (k=2 gives an A/B test its variant B)."""
    arms = _get_all_arms()
    contexts = [build_context_vector(age_bracket, income_tier, channel, domain_category) for channel in active_channels]
    scored = sorted(
        ((sum(_ucb_score(arm, context) for context in contexts), arm["arm_index"]) for arm in arms),
        key=lambda pair: (-pair[0], pair[1]),
    )
    return [(index, *ARMS[index]) for _, index in scored[:k]]


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


def _arm_view(arm: dict, contexts: list[np.ndarray]) -> dict:
    """One arm's standing for this audience: expected reward, uncertainty bonus, history."""
    a_inv = np.linalg.inv(np.array(arm["a_matrix"]))
    theta = a_inv @ np.array(arm["b_vector"])
    # Averaged over the active channels so both terms stay on the 0-1 reward scale.
    expected = float(np.mean([theta @ x for x in contexts]))
    bonus = float(np.mean([ALPHA * np.sqrt(x @ a_inv @ x) for x in contexts]))
    pulls = int(arm.get("pulls") or 0)
    return {
        "arm_index": arm["arm_index"],
        "image_style": arm["image_style"],
        "copy_tone": arm["copy_tone"],
        "expected": round(expected, 3),
        "bonus": round(bonus, 3),
        "score": round(expected + bonus, 3),
        "pulls": pulls,
        "mean_reward": round(float(arm.get("total_reward") or 0) / pulls, 3) if pulls else None,
    }


def explain_choice(
    age_bracket: str, income_tier: str, domain_category: str, active_channels: list[str], chosen_index: int
) -> dict:
    """Why an arm was picked, for the "Why this ad?" panel: its expected reward,
    how much of its score is still exploration, and the runners-up."""
    contexts = [build_context_vector(age_bracket, income_tier, channel, domain_category) for channel in active_channels]
    views = sorted((_arm_view(arm, contexts) for arm in _get_all_arms()), key=lambda v: (-v["score"], v["arm_index"]))
    chosen = next(v for v in views if v["arm_index"] == chosen_index)
    return {
        "algorithm": "LinUCB",
        "alpha": ALPHA,
        "context": {"age_bracket": age_bracket, "income_tier": income_tier, "domain_category": domain_category, "channels": active_channels},
        "chosen": chosen,
        # Exploiting when the evidence outweighs the uncertainty bonus, exploring otherwise.
        "mode": "exploit" if chosen["expected"] >= chosen["bonus"] else "explore",
        "rank": views.index(chosen) + 1,
        "alternatives": [v for v in views if v["arm_index"] != chosen_index][:3],
        "arms_tried": sum(1 for v in views if v["pulls"]),
        "total_rounds": sum(v["pulls"] for v in views),
    }
