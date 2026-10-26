import os

from src.capabilities.distribution import post_reddit
from src.capabilities.email_engine import signup_line, with_signup_line
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState

TITLE_MAX_LEN = 80


def distribution_reddit_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    title = creative.copy_text[:TITLE_MAX_LEN]
    subreddit = state.get("reddit_subreddit") or os.environ.get("REDDIT_DEFAULT_SUBREDDIT", "test")
    body = with_signup_line(creative.copy_text, signup_line(state["campaign_id"]))
    url = post_reddit(state["campaign_id"], state["round_id"], subreddit, title, body, user_id=state["user_id"])
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], reddit_post_url=url)
    return {"reddit_post_url": url}
