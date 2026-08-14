from datetime import datetime, timezone

from src.capabilities.feedback_correction import run_feedback_correction
from src.db.supabase_client import get_campaign, insert_feedback, update_campaign
from src.graph.state import CampaignState
from src.tools.bandit import build_context_vector, update_arm
from src.tools.memory import write_embedding


def _update_bandit_and_memory(state: CampaignState) -> None:
    creative = state["creative"]
    metrics_result = state["metrics_result"]
    persona = state["primary_persona"]
    user_id = state.get("user_id")

    # Rejected variants never reach here at all (the graph short-circuits to
    # END on a gate/preflight rejection), and collect_metrics only populates
    # channel_rewards for channels actually (re)posted-to -- so both the
    # "no update for rejected variants" and "skipped channel excluded from
    # reward" rules already hold with no special-casing needed here.
    for channel, reward in metrics_result.channel_rewards.items():
        context = build_context_vector(persona.age_bracket, persona.income_tier, channel, state["domain_category"])
        update_arm(creative.arm_index, context, reward)

    if not user_id:
        return
    write_embedding(
        user_id, state["campaign_id"], state["round_id"], "idea_persona", state["idea"],
        outcome_reward=metrics_result.overall_reward,
    )
    write_embedding(
        user_id, state["campaign_id"], state["round_id"], "creative",
        f"{creative.copy_text} {creative.image_prompt}", outcome_reward=metrics_result.overall_reward,
    )


def feedback_correction_node(state: CampaignState) -> CampaignState:
    campaign = get_campaign(state["campaign_id"])
    metrics_result = state["metrics_result"]

    _update_bandit_and_memory(state)

    directive = run_feedback_correction(
        state["idea"],
        metrics_result,
        state["round_id"],
        campaign["max_rounds"],
        user_id=state.get("user_id"),
        target_language=state.get("target_language", "en"),
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
            # Reset per-round state so the new round's novelty/preflight loops
            # aren't immediately capped by the previous round's attempt counts.
            "preflight_attempt": 0,
            "best_creative": None,
            "best_preflight": None,
            "novelty_attempt": 0,
            "best_novel_creative": None,
            "best_novelty_score": None,
        }

    return {"continue_campaign": False}


def route_after_feedback(state: CampaignState) -> str:
    return "generate_creative" if state.get("continue_campaign") else "finalize"
