from src.capabilities.audience import generate_personas
from src.db.supabase_client import insert_personas
from src.graph.state import CampaignState


def audience_node(state: CampaignState) -> CampaignState:
    personas = generate_personas(state["idea"], state["feasibility"], user_id=state.get("user_id"))
    insert_personas(state["campaign_id"], state["user_id"], personas, primary_index=0)
    return {"personas": personas}
