import os

METRICS_WAIT_HOURS = float(os.environ.get("METRICS_WAIT_HOURS", "6"))
FREE_MAX_ROUNDS = 3
PAID_MAX_ROUNDS = 10
DURATION_BUFFER_FACTOR = 1.5
MAX_REGENERATION_ATTEMPTS = 3
BLUESKY_ENGAGEMENT_CAP = 50
REDDIT_ENGAGEMENT_CAP = 50


def max_rounds_for_tier(is_subscribed_or_byok: bool) -> int:
    return PAID_MAX_ROUNDS if is_subscribed_or_byok else FREE_MAX_ROUNDS


def max_duration_minutes_for(max_rounds: int) -> int:
    return round(max_rounds * METRICS_WAIT_HOURS * 60 * DURATION_BUFFER_FACTOR)
