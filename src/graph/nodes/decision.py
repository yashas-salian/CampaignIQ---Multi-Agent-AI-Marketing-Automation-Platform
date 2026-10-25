import logging

from src.capabilities.brand import brand_kit_for_campaign
from src.capabilities.decision import evaluate, inputs_from, save
from src.constants import max_duration_minutes_for
from src.db.supabase_client import get_campaign, update_campaign, update_campaign_status
from src.graph.state import CampaignState

logger = logging.getLogger("graph.decision")


def decision_node(state: CampaignState) -> CampaignState:
    """Should this campaign run at all? Runs after the research and personas,
    before Gate 1, so the approver sees the recommendation and why.

    A hard block (prohibited product, banned word, a claim that can't be
    substantiated, a broken link) ends the campaign here as 'blocked'. Every
    other outcome goes to Gate 1, where a person decides; TEST_SMALL also caps
    the campaign's rounds. If the engine itself fails, the campaign carries on
    to Gate 1 without a recommendation rather than stopping."""
    campaign_id = state["campaign_id"]
    try:
        campaign = get_campaign(campaign_id)
        kit = brand_kit_for_campaign(campaign_id)
        inputs = inputs_from(
            state["idea"], state.get("feasibility"), state.get("personas"),
            domain_category=state.get("domain_category", "other"), target_language=state.get("target_language", "en"),
            org_id=campaign.get("org_id"), campaign_id=campaign_id, cta_url=campaign.get("cta_url"),
            banned_terms=kit.forbidden_words if kit else (),
        )
        result = evaluate(inputs)
    except Exception as exc:
        logger.warning("decision engine failed for %s, continuing to Gate 1 without it: %s", campaign_id, exc)
        return {"decision": None}

    save(result, inputs, campaign_id=campaign_id, user_id=state.get("user_id"), org_id=campaign.get("org_id"))
    if result.hard_blocks:
        update_campaign_status(campaign_id, "blocked")
        return {"decision": result.model_dump(), "rejected": True}
    cap = result.constraints.get("max_rounds")
    if cap and (campaign.get("max_rounds") or cap) > cap:
        update_campaign(campaign_id, max_rounds=cap, max_duration_minutes=max_duration_minutes_for(cap))
    return {"decision": result.model_dump()}


def route_after_decision(state: CampaignState) -> str:
    return "end" if state.get("rejected") else "gate_1"
