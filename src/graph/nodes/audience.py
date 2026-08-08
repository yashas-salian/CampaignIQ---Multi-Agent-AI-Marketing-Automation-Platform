from src.capabilities.audience import generate_personas
from src.graph.state import CampaignState


def audience_node(state: CampaignState) -> CampaignState:
    return {"personas": generate_personas(state["idea"], state["feasibility"])}
