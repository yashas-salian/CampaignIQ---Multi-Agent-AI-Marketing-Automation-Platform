from pydantic import BaseModel

from src.capabilities.experiments import split_recipients, two_proportion_test
from src.constants import BLUESKY_ENGAGEMENT_CAP, REDDIT_ENGAGEMENT_CAP
from src.tools.bluesky_client import get_bluesky_metrics
from src.tools.reddit_client import get_reddit_metrics


class MetricsResult(BaseModel):
    channel_rewards: dict[str, float]
    overall_reward: float
    raw: dict[str, dict]


def _is_real_post_ref(value: str | None) -> bool:
    # Not a dry run, a dedup skip, or a failed/dead delivery (see capabilities/delivery.py).
    return bool(value) and not value.startswith(("DRY_RUN", "skipped", "failed:", "dead:"))


def collect_metrics(campaign_id: str, user_id: str, round_number: int, email_to: list[str] | None = None) -> MetricsResult:
    from src.db.supabase_client import get_click_count, get_iteration, upsert_metric

    iteration = get_iteration(campaign_id, round_number) or {}
    channel_rewards: dict[str, float] = {}
    raw: dict[str, dict] = {}

    bluesky_ref = iteration.get("bluesky_post_uri")
    if _is_real_post_ref(bluesky_ref):
        m = get_bluesky_metrics(bluesky_ref)
        raw["bluesky"] = m
        reward = min((m["likes"] + m["reposts"] + m["replies"]) / BLUESKY_ENGAGEMENT_CAP, 1.0)
        channel_rewards["bluesky"] = reward
        upsert_metric(campaign_id, user_id, round_number, "bluesky", m, reward)

    reddit_ref = iteration.get("reddit_post_url")
    if _is_real_post_ref(reddit_ref):
        m = get_reddit_metrics(reddit_ref)
        raw["reddit"] = m
        reward = min((m["score"] + m["num_comments"]) / REDDIT_ENGAGEMENT_CAP, 1.0)
        channel_rewards["reddit"] = reward
        upsert_metric(campaign_id, user_id, round_number, "reddit", m, reward)

    email_ref = iteration.get("email_id")
    email_ref_b = iteration.get("email_id_b")
    ab = _is_real_post_ref(email_ref_b)
    # A/B rounds sent each variant to half the list (split deterministically).
    list_a, list_b = split_recipients(email_to or []) if ab else (email_to or [], [])
    if _is_real_post_ref(email_ref):
        clicks = get_click_count(campaign_id, round_number)
        recipients = max(len(list_a), 1)
        m = {"clicks": clicks, "recipients": recipients}
        reward = min(clicks / recipients, 1.0)
        raw["email"] = m
        channel_rewards["email"] = reward
        upsert_metric(campaign_id, user_id, round_number, "email", m, reward)
    if ab:
        clicks_b = get_click_count(campaign_id, round_number, "email_b")
        recipients_b = max(len(list_b), 1)
        test = two_proportion_test(raw.get("email", {}).get("clicks", 0), max(len(list_a), 1), clicks_b, recipients_b)
        m = {"clicks": clicks_b, "recipients": recipients_b, "ab_test": test}
        reward = min(clicks_b / recipients_b, 1.0)
        raw["email_b"] = m
        channel_rewards["email_b"] = reward
        upsert_metric(campaign_id, user_id, round_number, "email_b", m, reward)

    overall_reward = sum(channel_rewards.values()) / len(channel_rewards) if channel_rewards else 0.0
    return MetricsResult(channel_rewards=channel_rewards, overall_reward=overall_reward, raw=raw)
