from src.capabilities.distribution import post_bluesky
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState


def distribution_bluesky_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    uri = post_bluesky(state["campaign_id"], state["round_id"], creative.copy_text, image_bytes=creative.image_bytes)
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], bluesky_post_uri=uri)
    return {"bluesky_post_uri": uri}
