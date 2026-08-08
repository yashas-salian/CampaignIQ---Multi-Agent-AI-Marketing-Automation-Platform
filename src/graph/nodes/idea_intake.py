import uuid

from src.capabilities.idea_intake import normalize_idea
from src.graph.state import CampaignState


def idea_intake_node(state: CampaignState) -> CampaignState:
    normalized = normalize_idea(state["idea"])
    return {
        "idea": normalized.idea,
        "domain_category": normalized.domain_category,
        "campaign_id": state.get("campaign_id") or str(uuid.uuid4()),
        "round_id": state.get("round_id") or 1,
    }
