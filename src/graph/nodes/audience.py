from src.capabilities.audience import generate_personas
from src.capabilities.brand_memory import context_from_state, recall
from src.capabilities.email_engine import suggest_audience
from src.db.supabase_client import insert_personas
from src.graph.state import CampaignState


def audience_node(state: CampaignState) -> CampaignState:
    personas = generate_personas(
        state["idea"], state["feasibility"], user_id=state.get("user_id"),
        target_language=state.get("target_language", "en"),
        memory=recall(context_from_state(state)).section,  # e.g. audiences the organisation has learned to leave out
    )
    insert_personas(state["campaign_id"], state["user_id"], personas, primary_index=0)
    if state.get("org_id"):  # who should get the email, suggested for Gate 1 (from group names and counts only)
        suggest_audience(state["campaign_id"], state["org_id"], state["idea"], personas, state.get("target_language", "en"),
                         user_id=state.get("user_id"))
    return {"personas": personas}
