from src.capabilities.preflight import score_preflight
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState

MAX_PREFLIGHT_ATTEMPTS = 3


def preflight_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    result = score_preflight(creative, [state["primary_persona"]], user_id=state.get("user_id"))
    attempt = state.get("preflight_attempt", 0) + 1

    best_creative = state.get("best_creative")
    best_preflight = state.get("best_preflight")
    if best_preflight is None or result.predicted_engagement > best_preflight.predicted_engagement:
        best_creative, best_preflight = creative, result

    upsert_iteration(
        state["campaign_id"],
        state["user_id"],
        state["round_id"],
        copy_text=best_creative.copy_text,
        image_prompt=best_creative.image_prompt,
        preflight_score=best_preflight.predicted_engagement,
        preflight_passed=best_preflight.passed,
        preflight_attempt=attempt,
    )

    return {
        "creative": best_creative,
        "preflight": best_preflight,
        "preflight_attempt": attempt,
        "best_creative": best_creative,
        "best_preflight": best_preflight,
    }


def route_after_preflight(state: CampaignState) -> str:
    if state["preflight"].passed or state["preflight_attempt"] >= MAX_PREFLIGHT_ATTEMPTS:
        return "gate_2"
    return "generate_creative"
