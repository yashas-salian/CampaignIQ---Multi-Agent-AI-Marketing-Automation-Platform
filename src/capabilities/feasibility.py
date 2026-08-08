from pydantic import BaseModel

from src.providers.registry import get_llm
from src.tools.news import get_news_volume
from src.tools.reddit_client import search_reddit
from src.tools.trends import get_trend_interest

TREND_WEIGHT = 0.4
NEWS_WEIGHT = 0.3
REDDIT_WEIGHT = 0.3


class FeasibilityResult(BaseModel):
    score: int
    rationale: str
    signals: dict


def score_feasibility(idea: str) -> FeasibilityResult:
    trend = get_trend_interest(idea)
    news = get_news_volume(idea)
    reddit = search_reddit(idea)

    trend_score = trend["mean_interest"]
    news_score = min(news["total_results"], 100)
    reddit_score = min(reddit["avg_score"], 100)
    composite = round(TREND_WEIGHT * trend_score + NEWS_WEIGHT * news_score + REDDIT_WEIGHT * reddit_score)

    signals = {"trend": trend, "news": news, "reddit": reddit}
    rationale = get_llm().generate(
        f"An ad campaign idea is: \"{idea}\".\n"
        f"Research signals gathered: {signals}\n"
        f"The computed feasibility score (0-100) is {composite}.\n"
        "Write a 2-3 sentence rationale explaining what these signals suggest "
        "about this campaign's real-world momentum and feasibility.",
        system="You are a marketing analyst writing terse, evidence-grounded feasibility rationales.",
    )

    return FeasibilityResult(score=composite, rationale=rationale, signals=signals)
