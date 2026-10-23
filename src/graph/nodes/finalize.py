from src.capabilities.feedback_correction import build_campaign_summary
from src.capabilities.playbooks import refresh_after_campaign
from src.db.supabase_client import update_campaign
from src.graph.state import CampaignState


def finalize_node(state: CampaignState) -> CampaignState:
    summary = build_campaign_summary(state["campaign_id"])
    update_campaign(state["campaign_id"], status="completed", campaign_summary=summary)
    # What this campaign taught goes into its industry's playbook for next time.
    refresh_after_campaign(state["campaign_id"], user_id=state.get("user_id"))
    return {}
