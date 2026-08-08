from src.capabilities.distribution import post_bluesky
from src.graph.state import CampaignState


def distribution_bluesky_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    uri = post_bluesky(state["campaign_id"], state["round_id"], creative.copy_text, image_bytes=creative.image_bytes)
    return {"bluesky_post_uri": uri}
