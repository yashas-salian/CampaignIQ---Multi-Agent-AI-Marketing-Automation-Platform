from src.capabilities.distribution import post_bluesky
from src.capabilities.guardrails import prepare_for_channel
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState


def distribution_bluesky_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    text, blocked = prepare_for_channel(
        creative.copy_text, "bluesky", domain_category=state.get("domain_category", "other"), cta_url=state.get("cta_url")
    )
    if blocked:
        uri = f"dead: {blocked}"
    else:
        uri = post_bluesky(state["campaign_id"], state["round_id"], text, image_bytes=creative.image_bytes, user_id=state["user_id"])
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], bluesky_post_uri=uri)
    return {"bluesky_post_uri": uri}
