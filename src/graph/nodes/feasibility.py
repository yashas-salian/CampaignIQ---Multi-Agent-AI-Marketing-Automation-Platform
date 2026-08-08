from src.capabilities.feasibility import score_feasibility
from src.graph.state import CampaignState


def feasibility_node(state: CampaignState) -> CampaignState:
    return {"feasibility": score_feasibility(state["idea"])}
