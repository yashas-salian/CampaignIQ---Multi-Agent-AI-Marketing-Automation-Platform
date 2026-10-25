from src.capabilities.feasibility import score_feasibility
from src.constants import max_duration_minutes_for, max_rounds_for_tier
from src.db.supabase_client import create_campaign, update_campaign
from src.graph.state import CampaignState
from src.providers.registry import has_paid_tier_access


def feasibility_node(state: CampaignState) -> CampaignState:
    target_language = state.get("target_language", "en")
    result = score_feasibility(state["idea"], user_id=state.get("user_id"), target_language=target_language)
    max_rounds = max_rounds_for_tier(has_paid_tier_access(state.get("user_id")))
    create_campaign(
        state["campaign_id"],
        state["user_id"],
        state["idea"],
        state["domain_category"],
        result.score,
        result.rationale,
        reddit_subreddit=state.get("reddit_subreddit"),
        email_to=state.get("email_to"),
        cta_url=state.get("cta_url"),
        use_image_template=state.get("use_image_template", False),
        use_email_template=state.get("use_email_template", False),
        max_rounds=max_rounds,
        max_duration_minutes=max_duration_minutes_for(max_rounds),
        target_language=target_language,
        org_id=state.get("org_id"),
        ab_test=bool(state.get("ab_test")),
        product_image_path=state.get("product_image_path"),
        product_tagline=state.get("product_tagline"),
    )
    _start_market_watch(state["campaign_id"], result.signals, target_language)
    return {"feasibility": result}


def _start_market_watch(campaign_id: str, signals: dict, language: str) -> None:
    # Launch-time signals become the baseline the market-moment sweep compares against.
    trend, news = signals.get("trend") or {}, signals.get("news") or {}
    keyword = trend.get("keyword") or news.get("keyword")
    if not keyword:
        return
    try:
        update_campaign(campaign_id, market_watch={
            "keyword": keyword,
            "language": language,
            "baseline": {"trend_mean": trend.get("mean_interest"), "news_total": news.get("total_results")},
            "checked_at": None,
        })
    except Exception:  # alerts are a bonus; never fail the campaign over them
        pass
