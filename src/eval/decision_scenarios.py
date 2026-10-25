"""A fixed suite of campaign situations for the decision engine
(src/capabilities/decision.py), each with the decision a careful marketer would
make and why. Used by tests/unit/test_decision.py (reproducibility and the
hard-block invariant) and src/eval/decision_benchmark.py (engine vs the
"launch whenever feasibility passes" baseline).

The labels are hand-written judgements, and the engine's thresholds were set
alongside them: agreement here is a consistency check, not independent proof.
Real-world validation comes from `campaign_decisions.outcome` over time.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.capabilities.decision import DecisionInputs

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(minutes=5)).isoformat()
OLD = (NOW - timedelta(days=5)).isoformat()

BUY = ["Where can I buy one of these?", "Just ordered mine, free shipping too", "Any discount code for this?",
       "Subscribed to the monthly plan today", "Pre-order is open, grabbing two"]
COMPARE = ["Which is the best one for beginners?", "Honest review after a month", "Brand A vs brand B?",
           "Is it worth it at that price?"]
NEUTRAL = ["Saw this on the news today", "My cat sat on it lol", "Throwback to last summer", "Big conference this week",
           "That meme again", "Weather is wild", "New episode tonight", "Thread about history", "Good morning everyone",
           "Traffic was terrible", "Reading a book about it", "Fun fact about this", "Nice photo"]
REACH = "Bluesky and email newsletters"
UNREACHABLE = "Instagram reels and TikTok"


def texts(buy: int = 0, compare: int = 0, neutral: int = 0) -> list[str]:
    def take(pool, n):
        return [pool[k % len(pool)] + ("" if k < len(pool) else f" ({k})") for k in range(n)]
    return take(BUY, buy) + take(COMPARE, compare) + take(NEUTRAL, neutral)


def feasibility(trend_mean: float, news_total: int, community_avg: float) -> int:
    """Same composite as src/capabilities/feasibility.py (40% trend, 30% news, 30% community)."""
    return round(0.4 * trend_mean + 0.3 * min(news_total, 100) + 0.3 * min(community_avg, 100))


def make(
    idea: str, *, domain="other", trend=(50, 45, True), news=50, intent=(3, 2, 10), reach=(3, 3), history=None,
    trend_failed=False, news_failed=False, fetched=FRESH, destination=None, banned=(), language="en", community_avg=10.0,
) -> DecisionInputs:
    latest, mean, up = trend
    personas = [{"channel_fit": REACH}] * reach[0] + [{"channel_fit": UNREACHABLE}] * (reach[1] - reach[0])
    return DecisionInputs(
        idea=idea, domain_category=domain, target_language=language,
        feasibility_score=feasibility(0 if trend_failed else mean, 0 if news_failed else news, community_avg),
        keyword=idea.split(" for ")[0][:40],
        trend={"rate_limited": True, "mean_interest": 0, "latest_interest": 0, "fetched_at": fetched} if trend_failed
        else {"mean_interest": mean, "latest_interest": latest, "trending_up": up, "fetched_at": fetched},
        news={"error": "NewsAPI 429", "total_results": 0, "headlines": [], "fetched_at": fetched} if news_failed
        else {"total_results": news, "headlines": [], "fetched_at": fetched},
        community=[{"source": "Bluesky search", "result_count": 25, "avg_score": community_avg, "texts": texts(*intent),
                    "fetched_at": fetched}],
        personas=personas, active_channels=["bluesky", "email"], history=history,
        cta_url="https://example.com/shop" if destination else None, destination=destination, banned_terms=list(banned),
    )


@dataclass
class Scenario:
    id: str
    expected: str
    why: str
    inputs: DecisionInputs


GOOD = {"campaigns": 4, "mean_reward": 0.12}
SCENARIOS: list[Scenario] = [
    Scenario("strong_everything", "LAUNCH", "High, rising demand; people talk about buying; reachable; it has worked before.",
             make("Insulated steel water bottles for hikers", trend=(75, 60, True), news=80, intent=(5, 3, 8), history=GOOD)),
    Scenario("strong_no_history", "LAUNCH", "Strong market signals; no history yet is a gap, not a red flag.",
             make("Meal-prep kits for night-shift nurses", trend=(70, 60, True), news=60, intent=(5, 2, 8))),
    Scenario("trending_no_buyers", "TEST_SMALL", "Everyone talks about it, nobody wants to buy, and coverage is crowded: test, don't commit.",
             make("Merch for the viral dancing cat", trend=(85, 70, True), news=3000, intent=(0, 0, 14), reach=(2, 3))),
    Scenario("niche_with_buyers", "TEST_SMALL", "Tiny search demand but the few who talk about it want to buy, and no competitors: a small test.",
             make("Left-handed calligraphy pens", trend=(8, 6, True), news=3, intent=(6, 2, 4))),
    Scenario("dead_market", "KILL", "No demand, falling, nobody buying, hard to reach.",
             make("Fax machine refurbishing service", trend=(2, 3, False), news=0, intent=(0, 0, 8), reach=(1, 3))),
    Scenario("rising_early_weak", "WAIT", "Interest has tripled but is still low and nobody is buying yet: re-check when it peaks.",
             make("Padel racket grips", trend=(25, 8, True), news=10, intent=(0, 1, 13), reach=(2, 3))),
    Scenario("rising_with_buyers", "TEST_SMALL", "Fast-rising topic with real buying talk: get in early, but small.",
             make("Electrolyte gummies for runners", trend=(25, 8, True), news=10, intent=(4, 2, 6), reach=(2, 3))),
    Scenario("prohibited_weapons", "KILL", "Ad platforms don't allow advertising firearms, whatever the demand.",
             make("Online store selling pistols and ammunition", trend=(80, 70, True), news=90, intent=(6, 2, 4), history=GOOD)),
    Scenario("counterfeit", "KILL", "Counterfeit goods: prohibited.",
             make("Replica designer bags at a tenth of the price", trend=(60, 50, True), news=40, intent=(6, 3, 4))),
    Scenario("miracle_cure", "KILL", "An unsubstantiable medical claim in the product itself.",
             make("Herbal tea that cures diabetes", domain="healthcare", trend=(55, 50, True), news=60, intent=(4, 2, 6))),
    Scenario("guaranteed_returns", "KILL", "Promising guaranteed investment returns is illegal advertising.",
             make("Trading course with guaranteed returns every month", domain="finance_fintech", trend=(60, 55, True),
                  news=70, intent=(5, 3, 6), history=GOOD)),
    Scenario("broken_link", "KILL", "Great opportunity, but the call-to-action link doesn't exist: fix it first.",
             make("Insulated steel water bottles for hikers", trend=(75, 60, True), news=80, intent=(5, 3, 8),
                  destination={"status": "invalid", "detail": "shop.example doesn't exist"})),
    Scenario("banned_word", "KILL", "Uses a word the brand has banned.",
             make("Cheap sunglasses for festival season", trend=(60, 50, True), news=50, intent=(5, 2, 6), banned=["cheap"])),
    Scenario("no_signals", "INSUFFICIENT_EVIDENCE", "Trends and news both failed and there's barely any conversation.",
             make("Artisanal ice for cocktails", trend_failed=True, news_failed=True, intent=(0, 0, 2))),
    Scenario("stale_signals", "INSUFFICIENT_EVIDENCE", "Everything was measured five days ago: refresh before deciding.",
             make("Insulated steel water bottles for hikers", trend=(75, 60, True), news=80, intent=(5, 3, 8), fetched=OLD)),
    Scenario("demand_missing_rest_good", "TEST_SMALL", "Search data unavailable; buying talk and history are good: test rather than launch blind.",
             make("Refillable eco cleaning kits", trend_failed=True, news=60, intent=(5, 2, 6), history={"campaigns": 3, "mean_reward": 0.12})),
    Scenario("saturated_big_demand", "TEST_SMALL", "Huge demand and buyers, but the space is crowded: test a differentiated angle first.",
             make("Wireless earbuds for the gym", trend=(85, 80, False), news=5000, intent=(4, 3, 7), history={"campaigns": 3, "mean_reward": 0.05})),
    Scenario("unreachable_audience", "TEST_SMALL", "Good market, but the audience lives on channels we don't post to.",
             make("Skincare for teen gamers", trend=(50, 45, True), news=40, intent=(4, 2, 6), reach=(0, 3))),
    Scenario("proven_category", "LAUNCH", "Moderate market, and this organisation's campaigns in the category do well.",
             make("Weekend cooking classes", trend=(35, 30, True), news=30, intent=(3, 1, 9), reach=(2, 3),
                  history={"campaigns": 5, "mean_reward": 0.2})),
    Scenario("poor_track_record", "TEST_SMALL", "Same moderate market, but past campaigns in the category flopped.",
             make("Weekend cooking classes", trend=(35, 30, True), news=30, intent=(3, 1, 9), reach=(2, 3),
                  history={"campaigns": 4, "mean_reward": 0.01})),
    Scenario("falling_market", "KILL", "Interest has collapsed to a quarter of its average and buying talk is thin.",
             make("Fidget spinners", trend=(10, 40, False), news=100, intent=(1, 0, 13), reach=(2, 3))),
    Scenario("few_posts", "TEST_SMALL", "Decent demand but too few posts to judge buying intent: test.",
             make("Bamboo toothbrush subscription", trend=(40, 35, True), news=20, intent=(1, 0, 2), reach=(2, 3))),
    Scenario("claim_needs_review", "LAUNCH", "Strong market; 'clinically proven' isn't a block, but needs evidence before it's in an ad.",
             make("Clinically proven sleep mask", trend=(70, 60, True), news=60, intent=(5, 2, 8), history=GOOD)),
    Scenario("link_unverified", "LAUNCH", "Strong market; the link timed out once, which is flagged but doesn't block.",
             make("Insulated steel water bottles for hikers", trend=(75, 60, True), news=80, intent=(5, 3, 8),
                  destination={"status": "unverified", "detail": "the site didn't answer in time"})),
    Scenario("hindi_market", "TEST_SMALL", "Hindi-language market with buying talk, moderate demand and no history.",
             make("Ayurvedic hair oil for students", trend=(30, 25, True), news=15, language="hi", intent=(0, 0, 0))),
]

# The Hindi scenario's conversation is in Hindi.
SCENARIOS[-1].inputs.community[0]["texts"] = ["यह तेल कहाँ से खरीद सकते हैं?", "ऑर्डर कर दिया, कल आएगा", "कीमत कितनी है?",
                                              "सबसे अच्छा हेयर ऑयल कौन सा है?", "आज बारिश हो रही है", "नया गाना सुना",
                                              "कॉलेज में परीक्षा है", "सुबह की चाय"]
