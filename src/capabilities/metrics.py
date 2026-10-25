import logging

from pydantic import BaseModel

from src.capabilities.experiments import bayesian_ab, split_recipients, two_proportion_test
from src.constants import BLUESKY_ENGAGEMENT_CAP, MASTODON_ENGAGEMENT_CAP, REDDIT_ENGAGEMENT_CAP
from src.tools.bluesky_client import get_bluesky_metrics
from src.tools.mastodon_client import get_mastodon_metrics
from src.tools.reddit_client import get_reddit_metrics


logger = logging.getLogger("capabilities.metrics")


class MetricsResult(BaseModel):
    channel_rewards: dict[str, float]
    overall_reward: float
    raw: dict[str, dict]


def _is_real_post_ref(value: str | None) -> bool:
    # Not a dry run, a dedup skip, or a failed/dead delivery (see capabilities/delivery.py).
    return bool(value) and not value.startswith(("DRY_RUN", "skipped", "failed:", "dead:"))


def collect_metrics(campaign_id: str, user_id: str, round_number: int, email_to: list[str] | None = None) -> MetricsResult:
    """Each channel is collected on its own: one API failing (an outage, an
    expired token) never loses the others' numbers. A channel that couldn't be
    read is left out of the rewards ("not measured"), never counted as zero,
    and its metric row isn't written, so a rerun simply fills it in."""
    from src.db.supabase_client import get_click_count, get_iteration, upsert_metric

    iteration = get_iteration(campaign_id, round_number) or {}
    channel_rewards: dict[str, float] = {}
    raw: dict[str, dict] = {}

    def record(channel: str, read) -> None:
        try:
            m, reward = read()
        except Exception as exc:
            logger.warning("metrics for %s (campaign %s, round %s) unavailable: %s", channel, campaign_id, round_number, exc)
            return
        raw[channel] = m
        channel_rewards[channel] = reward
        try:
            upsert_metric(campaign_id, user_id, round_number, channel, m, reward)
        except Exception as exc:  # the reward still counts for this round's decision
            logger.warning("storing %s metrics failed: %s", channel, exc)

    def social(fetch, ref: str, cap: int, keys: tuple[str, ...]):
        def read():
            m = fetch(ref)
            return m, min(sum(m[k] for k in keys) / cap, 1.0)
        return read

    bluesky_ref = iteration.get("bluesky_post_uri")
    if _is_real_post_ref(bluesky_ref):
        record("bluesky", social(get_bluesky_metrics, bluesky_ref, BLUESKY_ENGAGEMENT_CAP, ("likes", "reposts", "replies")))

    mastodon_ref = iteration.get("mastodon_post_url")
    if _is_real_post_ref(mastodon_ref):
        record("mastodon", social(get_mastodon_metrics, mastodon_ref, MASTODON_ENGAGEMENT_CAP, ("likes", "reposts", "replies")))

    reddit_ref = iteration.get("reddit_post_url")
    if _is_real_post_ref(reddit_ref):
        record("reddit", social(get_reddit_metrics, reddit_ref, REDDIT_ENGAGEMENT_CAP, ("score", "num_comments")))

    email_ref = iteration.get("email_id")
    email_ref_b = iteration.get("email_id_b")
    ab = _is_real_post_ref(email_ref_b)
    # A/B rounds sent each variant to half the list (the same split as the send).
    list_a, list_b = split_recipients(email_to or [], salt=campaign_id) if ab else (email_to or [], [])
    if _is_real_post_ref(email_ref):
        def read_email():
            clicks = get_click_count(campaign_id, round_number)
            recipients = max(len(list_a), 1)
            return {"clicks": clicks, "recipients": recipients}, min(clicks / recipients, 1.0)

        record("email", read_email)
    if ab and "email" in raw:
        def read_email_b():
            clicks_b = get_click_count(campaign_id, round_number, "email_b")
            recipients_b = max(len(list_b), 1)
            clicks_a = raw["email"]["clicks"]
            test = two_proportion_test(clicks_a, max(len(list_a), 1), clicks_b, recipients_b)
            test["bayes"] = bayesian_ab(clicks_a, len(list_a), clicks_b, len(list_b))
            return {"clicks": clicks_b, "recipients": recipients_b, "ab_test": test}, min(clicks_b / recipients_b, 1.0)

        record("email_b", read_email_b)

    overall_reward = sum(channel_rewards.values()) / len(channel_rewards) if channel_rewards else 0.0
    return MetricsResult(channel_rewards=channel_rewards, overall_reward=overall_reward, raw=raw)
