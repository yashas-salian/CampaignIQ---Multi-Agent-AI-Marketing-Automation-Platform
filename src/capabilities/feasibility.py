import logging
import os

from pydantic import BaseModel

from src.providers.registry import get_llm
from src.tools.bluesky_client import search_bluesky
from src.tools.mastodon_client import search_mastodon
from src.tools.news import get_news_volume
from src.tools.reddit_client import search_reddit
from src.tools.trends import get_trend_interest

logger = logging.getLogger("capabilities.feasibility")

TREND_WEIGHT = 0.4
NEWS_WEIGHT = 0.3
# Community signal: an average of Bluesky + Mastodon search results (Reddit is
# on hold — API access blocked by policy changes — but blends in here too if
# ENABLE_REDDIT is ever set back to true; its code stays intact either way).
COMMUNITY_WEIGHT = 0.3


def _reddit_enabled() -> bool:
    return os.environ.get("ENABLE_REDDIT", "false").lower() == "true"


class FeasibilityResult(BaseModel):
    score: int
    rationale: str
    signals: dict


def _extract_search_keywords(idea: str, user_id: str | None) -> str:
    response = get_llm(user_id).generate(
        f'Campaign idea: "{idea}"\n\n'
        "Extract a short 2-4 word search keyword phrase capturing the core product/topic — suitable "
        "as a Google Trends / news search query, not a full sentence. Respond with ONLY the keyword "
        "phrase itself: no quotes, no prose, no punctuation.",
        system="You output only a short keyword phrase, nothing else.",
    )
    return response.strip().strip('"')


def _safe_signal(fetch_fn, keyword: str, neutral: dict) -> dict:
    # Free/public signal sources (Bluesky, Mastodon, NewsAPI, Reddit) can time
    # out or error transiently — degrade that one signal to neutral rather
    # than crashing the whole feasibility/campaign run over it.
    try:
        return fetch_fn(keyword)
    except Exception as exc:
        logger.warning("%s failed for %r: %s", getattr(fetch_fn, "__name__", fetch_fn), keyword, exc)
        return {**neutral, "keyword": keyword, "error": str(exc)}


def score_feasibility(idea: str, *, user_id: str | None = None) -> FeasibilityResult:
    keywords = _extract_search_keywords(idea, user_id)
    trend = get_trend_interest(keywords)  # has its own internal retry + graceful fallback
    news = _safe_signal(get_news_volume, keywords, {"total_results": 0, "headlines": []})
    bluesky = _safe_signal(search_bluesky, keywords, {"result_count": 0, "avg_score": 0.0, "avg_comments": 0.0})

    trend_score = trend["mean_interest"]
    news_score = min(news["total_results"], 100)
    bluesky_score = min(bluesky["avg_score"], 100)
    community_scores = [bluesky_score]

    signals = {"trend": trend, "news": news, "bluesky": bluesky}

    # Unauthenticated Mastodon status search is unreliable (confirmed: most
    # instances return empty results for any keyword without a token) — only
    # fold it into the composite once MASTODON_ACCESS_TOKEN is configured, so
    # a non-functional fetch can't silently drag every score toward zero.
    if os.environ.get("MASTODON_ACCESS_TOKEN"):
        mastodon = _safe_signal(search_mastodon, keywords, {"result_count": 0, "avg_score": 0.0, "avg_comments": 0.0})
        signals["mastodon"] = mastodon
        community_scores.append(min(mastodon["avg_score"], 100))

    if _reddit_enabled():
        reddit = _safe_signal(search_reddit, keywords, {"result_count": 0, "avg_score": 0.0, "avg_comments": 0.0})
        signals["reddit"] = reddit
        community_scores.append(min(reddit["avg_score"], 100))

    community_score = sum(community_scores) / len(community_scores)
    composite = round(TREND_WEIGHT * trend_score + NEWS_WEIGHT * news_score + COMMUNITY_WEIGHT * community_score)

    rationale = get_llm(user_id).generate(
        f"An ad campaign idea is: \"{idea}\".\n"
        f"Research signals gathered: {signals}\n"
        f"The computed feasibility score (0-100) is {composite}.\n"
        "Write a 2-3 sentence rationale explaining what these signals suggest "
        "about this campaign's real-world momentum and feasibility.",
        system="You are a marketing analyst writing terse, evidence-grounded feasibility rationales.",
    )

    return FeasibilityResult(score=composite, rationale=rationale, signals=signals)
