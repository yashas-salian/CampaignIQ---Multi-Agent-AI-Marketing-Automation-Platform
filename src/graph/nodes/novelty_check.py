from src.graph.state import CampaignState
from src.tools.memory import novelty_score

MAX_NOVELTY_ATTEMPTS = 3
NOVELTY_SIMILARITY_THRESHOLD = 0.85  # above this, treat as a near-duplicate


def novelty_check_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    user_id = state.get("user_id")
    attempt = state.get("novelty_attempt", 0) + 1

    similarity = novelty_score(user_id, f"{creative.copy_text} {creative.image_prompt}") if user_id else 0.0

    best_creative = state.get("best_novel_creative")
    best_similarity = state.get("best_novelty_score")
    if best_similarity is None or similarity < best_similarity:
        best_creative, best_similarity = creative, similarity

    return {
        "creative": best_creative,
        "novelty_attempt": attempt,
        "best_novel_creative": best_creative,
        "best_novelty_score": best_similarity,
    }


def route_after_novelty_check(state: CampaignState) -> str:
    if state["best_novelty_score"] < NOVELTY_SIMILARITY_THRESHOLD or state["novelty_attempt"] >= MAX_NOVELTY_ATTEMPTS:
        return "run_preflight"
    return "generate_creative"
