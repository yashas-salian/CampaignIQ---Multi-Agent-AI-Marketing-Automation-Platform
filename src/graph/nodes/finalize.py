from src.capabilities.feedback_correction import build_campaign_summary
from src.db.supabase_client import update_campaign
from src.graph.state import CampaignState


def finalize_node(state: CampaignState) -> CampaignState:
    summary = build_campaign_summary(state["campaign_id"])
    update_campaign(state["campaign_id"], status="completed", campaign_summary=summary)
    return {}
