from src.capabilities.feasibility import score_feasibility
from src.db.supabase_client import create_campaign
from src.graph.state import CampaignState


def feasibility_node(state: CampaignState) -> CampaignState:
    result = score_feasibility(state["idea"])
    create_campaign(
        state["campaign_id"],
        state["idea"],
        state["domain_category"],
        result.score,
        result.rationale,
        reddit_subreddit=state.get("reddit_subreddit"),
        email_to=state.get("email_to"),
        cta_url=state.get("cta_url"),
    )
    return {"feasibility": result}
