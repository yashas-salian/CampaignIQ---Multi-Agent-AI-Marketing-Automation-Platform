from datetime import datetime, timezone

from src.capabilities.feedback_correction import run_feedback_correction
from src.db.supabase_client import get_campaign, insert_feedback, update_campaign
from src.graph.state import CampaignState


def feedback_correction_node(state: CampaignState) -> CampaignState:
    campaign = get_campaign(state["campaign_id"])
    metrics_result = state["metrics_result"]

    directive = run_feedback_correction(
        state["idea"],
        metrics_result,
        state["round_id"],
        campaign["max_rounds"],
        user_id=state.get("user_id"),
    )

    created_at = datetime.fromisoformat(campaign["created_at"])
    elapsed_minutes = (datetime.now(timezone.utc) - created_at).total_seconds() / 60
    continue_campaign = (
        directive.continue_campaign
        and elapsed_minutes < campaign["max_duration_minutes"]
        and not campaign.get("stop_requested")
    )

    insert_feedback(
        state["campaign_id"],
        state["user_id"],
        state["round_id"],
        overall_reward=metrics_result.overall_reward,
        stakeholder_comment=None,
        revision_directive=directive.model_dump(),
        continued=continue_campaign,
    )

    if continue_campaign:
        next_round = state["round_id"] + 1
        update_campaign(state["campaign_id"], status="awaiting_next_round", current_round=next_round, distributed_at=None)
        return {
            "round_id": next_round,
            "continue_campaign": True,
            "revision_directive": directive.adjustments,
            # Reset per-round state so the new round's preflight loop isn't
            # immediately capped by the previous round's attempt count.
            "preflight_attempt": 0,
            "best_creative": None,
            "best_preflight": None,
        }

    return {"continue_campaign": False}


def route_after_feedback(state: CampaignState) -> str:
    return "generate_creative" if state.get("continue_campaign") else "finalize"
