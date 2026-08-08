from src.capabilities.creative import generate_creative
from src.graph.state import CampaignState


def creative_node(state: CampaignState) -> CampaignState:
    return {"creative": generate_creative(state["idea"], state["primary_persona"])}
