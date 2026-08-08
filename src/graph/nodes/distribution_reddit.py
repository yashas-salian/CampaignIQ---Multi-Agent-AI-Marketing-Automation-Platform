import os

from src.capabilities.distribution import post_reddit
from src.graph.state import CampaignState

TITLE_MAX_LEN = 80


def distribution_reddit_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    title = creative.copy_text[:TITLE_MAX_LEN]
    subreddit = state.get("reddit_subreddit") or os.environ.get("REDDIT_DEFAULT_SUBREDDIT", "test")
    url = post_reddit(state["campaign_id"], state["round_id"], subreddit, title, creative.copy_text)
    return {"reddit_post_url": url}
