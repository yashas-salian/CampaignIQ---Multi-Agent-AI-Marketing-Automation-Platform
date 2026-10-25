import logging
import os
from datetime import datetime, timezone

from pydantic import BaseModel

from src.languages import language_name, newsapi_language, trends_hl
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import drop_suspicious, fence
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


def _extract_search_keywords(idea: str, user_id: str | None, target_language: str) -> str:
    # Localizes the research-signal query so Trends/News/community search
    # reflect the target market's language, not always English -- one LLM
    # call produces both, since the English phrase is a useful anchor even
    # when target_language != "en".
    prompt, system = PROMPTS["feasibility.keywords"].render(
        idea=fence(idea, "user_idea"), language=language_name(target_language)
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)
    if target_language == "en":
        return str(parsed["keywords_en"]).strip().strip('"')
    return str(parsed["keywords_localized"]).strip().strip('"')


def _safe_signal(fetch_fn, keyword: str, neutral: dict, **kwargs) -> dict:
    # Free/public signal sources (Bluesky, Mastodon, NewsAPI, Reddit) can time
    # out or error transiently — degrade that one signal to neutral rather
    # than crashing the whole feasibility/campaign run over it.
    try:
        return fetch_fn(keyword, **kwargs)
    except Exception as exc:
        logger.warning("%s failed for %r: %s", getattr(fetch_fn, "__name__", fetch_fn), keyword, exc)
        return {**neutral, "keyword": keyword, "error": str(exc)}


def score_feasibility(idea: str, *, user_id: str | None = None, target_language: str = "en") -> FeasibilityResult:
    keywords = _extract_search_keywords(idea, user_id, target_language)
    trend = get_trend_interest(keywords, hl=trends_hl(target_language))  # has its own internal retry + graceful fallback
    news = _safe_signal(
        get_news_volume, keywords, {"total_results": 0, "headlines": []}, language=newsapi_language(target_language)
    )
    bluesky = _safe_signal(search_bluesky, keywords, {"result_count": 0, "avg_score": 0.0, "avg_comments": 0.0})

    trend_score = trend["mean_interest"]
    news_score = min(news["total_results"], 100)
    bluesky_score = min(bluesky["avg_score"], 100)
    community_scores = [bluesky_score]

    # Headlines are third-party text that goes into the rationale prompt:
    # drop any that read like instructions to the model.
    headlines = news.get("headlines") or []
    safe_headlines = drop_suspicious([str(h) for h in headlines], "news headlines")
    if len(safe_headlines) != len(headlines):
        news = {**news, "headlines": safe_headlines, "headlines_dropped": len(headlines) - len(safe_headlines)}
    signals = {"trend": trend, "news": news, "bluesky": bluesky}
    fetched_at = datetime.now(timezone.utc).isoformat()

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

    # When each signal was read, so the decision engine can tell fresh evidence from stale.
    for value in signals.values():
        value.setdefault("fetched_at", fetched_at)

    community_score = sum(community_scores) / len(community_scores)
    composite = round(TREND_WEIGHT * trend_score + NEWS_WEIGHT * news_score + COMMUNITY_WEIGHT * community_score)

    # Few-shot grounding only, not a scoring input -- keeps the composite
    # formula above fully transparent/auditable regardless of retrieval.
    similar_text = ""
    if user_id:
        # Lazy import: src.db.supabase_client imports capabilities.audience for
        # the Persona type, and capabilities.audience imports this module for
        # FeasibilityResult -- a module-level import of memory.py here (which
        # itself imports supabase_client) would create a circular import.
        from src.tools.memory import retrieve_similar

        similar = retrieve_similar(user_id, "idea_persona", idea, k=3)
        if similar:
            examples = "\n".join(f"- {m['content_text']} (outcome reward: {m.get('outcome_reward')})" for m in similar)
            similar_text = f"\nSimilar past campaigns from this user's own history:\n{fence(examples, 'campaign_history')}\n"

    prompt, system = PROMPTS["feasibility.rationale"].render(
        idea=fence(idea, "user_idea"),
        # Sample post texts are for the decision engine, not the rationale (and they're third-party text).
        signals=fence({k: {kk: vv for kk, vv in v.items() if kk not in ("texts", "fetched_at")} for k, v in signals.items()},
                      "research_signals", max_len=4000),
        similar=similar_text,
        score=composite,
        language=language_name(target_language),
    )
    rationale = get_llm(user_id).generate(prompt, system=system)

    return FeasibilityResult(score=composite, rationale=rationale, signals=signals)
