from datetime import datetime, timezone

from langgraph.types import interrupt

from src.constants import METRICS_WAIT_HOURS
from src.db.supabase_client import get_campaign, update_campaign
from src.graph.state import CampaignState


def metrics_wait_node(state: CampaignState) -> CampaignState:
    campaign = get_campaign(state["campaign_id"])
    if not campaign.get("distributed_at"):
        update_campaign(
            state["campaign_id"],
            status="awaiting_metrics",
            distributed_at=datetime.now(timezone.utc).isoformat(),
        )
    interrupt({"reason": "metrics_wait", "campaign_id": state["campaign_id"], "wait_hours": METRICS_WAIT_HOURS})
    return {}
