from src.db.supabase_client import update_campaign_status
from src.graph.state import CampaignState


def finalize_node(state: CampaignState) -> CampaignState:
    update_campaign_status(state["campaign_id"], "completed")
    return {}
