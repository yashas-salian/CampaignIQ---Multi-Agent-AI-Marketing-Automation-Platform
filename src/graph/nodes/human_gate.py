from langgraph.types import interrupt

from src.capabilities.audience import Persona
from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.db.supabase_client import create_pending_gate, get_campaign, get_primary_persona, update_campaign_status
from src.graph.state import CampaignState


def gate_1_node(state: CampaignState) -> CampaignState:
    create_pending_gate(state["campaign_id"], state["user_id"], gate_number=1, round_number=state["round_id"])
    update_campaign_status(state["campaign_id"], "awaiting_gate_1")

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
        ),
        "rejected": False,
    }


def gate_2_node(state: CampaignState) -> CampaignState:
    create_pending_gate(state["campaign_id"], state["user_id"], gate_number=2, round_number=state["round_id"])
    update_campaign_status(state["campaign_id"], "awaiting_gate_2")

    decision = interrupt({"gate_number": 2, "campaign_id": state["campaign_id"]})

    if decision["decision"] == "reject":
        update_campaign_status(state["campaign_id"], "rejected")
        return {"rejected": True}

    return {"rejected": False}
