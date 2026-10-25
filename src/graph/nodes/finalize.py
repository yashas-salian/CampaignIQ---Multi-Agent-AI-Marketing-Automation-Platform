from src.capabilities.decision import record_outcome
from src.capabilities.feedback_correction import build_campaign_summary
from src.capabilities.playbooks import refresh_after_campaign
from src.db.supabase_client import update_campaign
from src.graph.state import CampaignState


def finalize_node(state: CampaignState) -> CampaignState:
    summary = build_campaign_summary(state["campaign_id"])
    update_campaign(state["campaign_id"], status="completed", campaign_summary=summary)
    # What actually happened, next to what the decision engine recommended.
    record_outcome(state["campaign_id"], summary)
    # What this campaign taught goes into its industry's playbook for next time.
    refresh_after_campaign(state["campaign_id"], user_id=state.get("user_id"))
    return {}
