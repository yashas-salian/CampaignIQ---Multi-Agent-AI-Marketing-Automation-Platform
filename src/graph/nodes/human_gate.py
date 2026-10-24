import logging

from langgraph.types import interrupt

from src.capabilities.audience import Persona
from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.db.supabase_client import (
    AD_IMAGES_BUCKET,
    create_pending_gate,
    download_object,
    get_campaign,
    get_iteration,
    get_primary_persona,
    update_campaign_status,
)
from src.graph.state import CampaignState
from src.notifications import notify_gate_opened

logger = logging.getLogger("graph.human_gate")


def gate_1_node(state: CampaignState) -> CampaignState:
    create_pending_gate(state["campaign_id"], state["user_id"], gate_number=1, round_number=state["round_id"])
    update_campaign_status(state["campaign_id"], "awaiting_gate_1")
    notify_gate_opened(state["campaign_id"], 1, state["round_id"])

    decision = interrupt({"gate_number": 1, "campaign_id": state["campaign_id"]})

    if decision["decision"] == "reject":
        update_campaign_status(state["campaign_id"], "rejected")
        return {"rejected": True}

    # Re-read from Supabase: an "edit" decision overwrites fields directly in the
    # DB via the frontend, so the graph must pick up the latest values here
    # rather than trust its own pre-gate in-memory state.
    campaign = get_campaign(state["campaign_id"])
    primary = get_primary_persona(state["campaign_id"])
    # The user may have corrected the category at Gate 1 (recorded in
    # domain_corrections). It's the bandit's domain context, so the rest of the
    # loop must use the corrected value -- validated, never trusted blindly.
    domain = campaign.get("domain_category")
    if domain not in DOMAIN_CATEGORIES:
        domain = state["domain_category"]
    return {
        "idea": campaign["idea"],
        "domain_category": domain,
        "primary_persona": Persona(
            name=primary["name"],
            demographics=primary["demographics"],
            psychographics=primary["psychographics"],
            channel_fit=primary["channel_fit"],
            messaging_angle=primary["messaging_angle"],
            age_bracket=primary["age_bracket"],
            income_tier=primary["income_tier"],
            archetype=primary.get("archetype") or "general",
            gender=primary.get("gender") or "unspecified",
        ),
        "rejected": False,
    }


def gate_2_node(state: CampaignState) -> CampaignState:
    create_pending_gate(state["campaign_id"], state["user_id"], gate_number=2, round_number=state["round_id"])
    update_campaign_status(state["campaign_id"], "awaiting_gate_2")
    notify_gate_opened(state["campaign_id"], 2, state["round_id"])

    decision = interrupt({"gate_number": 2, "campaign_id": state["campaign_id"]})

    if decision["decision"] == "reject":
        update_campaign_status(state["campaign_id"], "rejected")
        return {"rejected": True}

    # Approvers may have edited the copy at the gate (edit_round_copy, with a
    # version history): send what they approved, not the pre-gate draft.
    # Distribution re-runs the brand-safety check on the final text.
    iteration = get_iteration(state["campaign_id"], state["round_id"]) or {}
    update: dict = {"rejected": False}
    creative = state.get("creative")
    if creative is not None and iteration.get("copy_text") and iteration["copy_text"] != creative.copy_text:
        update["creative"] = creative.model_copy(update={"copy_text": iteration["copy_text"]})
    # A new picture painted at the gate (capability "ad_image") replaced the
    # stored ad: send that one. If it can't be read, the original still goes.
    if creative is not None and iteration.get("image_version") and iteration.get("image_path"):
        try:
            base = update.get("creative", creative)
            update["creative"] = base.model_copy(
                update={"image_bytes": download_object(AD_IMAGES_BUCKET, iteration["image_path"])}
            )
        except Exception as exc:
            logger.warning("repainted ad unreadable, sending the original: %s", exc)
    variant = state.get("creative_b")
    if variant is not None and iteration.get("copy_text_b") and iteration["copy_text_b"] != variant.copy_text:
        update["creative_b"] = variant.model_copy(update={"copy_text": iteration["copy_text_b"]})
    return update
