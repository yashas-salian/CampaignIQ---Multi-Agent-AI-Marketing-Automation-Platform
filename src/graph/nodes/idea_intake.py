from src.capabilities.idea_intake import normalize_idea
from src.graph.state import CampaignState


def idea_intake_node(state: CampaignState) -> CampaignState:
    normalized = normalize_idea(state["idea"], user_id=state.get("user_id"))
    return {
        "idea": normalized.idea,
        "domain_category": normalized.domain_category,
        "round_id": state.get("round_id") or 1,
    }
