import os

from src.capabilities.distribution import post_reddit
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState

TITLE_MAX_LEN = 80


def distribution_reddit_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    title = creative.copy_text[:TITLE_MAX_LEN]
    subreddit = state.get("reddit_subreddit") or os.environ.get("REDDIT_DEFAULT_SUBREDDIT", "test")
    url = post_reddit(state["campaign_id"], state["round_id"], subreddit, title, creative.copy_text)
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], reddit_post_url=url)
    return {"reddit_post_url": url}
