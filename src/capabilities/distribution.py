import os

from src.tools.bluesky_client import post_to_bluesky
from src.tools.dedup_store import already_sent, mark_sent
from src.tools.reddit_client import post_to_reddit
from src.tools.resend_client import send_email
from src.tools.track_click import wrap_tracked_url


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() == "true"


def post_bluesky(campaign_id: str, round_id: int, copy_text: str, image_bytes: bytes | None = None) -> str:
    channel = "bluesky"
    if already_sent(campaign_id, round_id, channel):
        return "skipped: already sent for this campaign/round"

    if _dry_run():
        result = f"DRY_RUN: would post to Bluesky: {copy_text[:60]!r}"
    else:
        result = post_to_bluesky(copy_text, image_bytes=image_bytes)

    mark_sent(campaign_id, round_id, channel, result)
    return result


def post_reddit(campaign_id: str, round_id: int, subreddit: str, title: str, body: str) -> str:
    channel = "reddit"
    if already_sent(campaign_id, round_id, channel):
        return "skipped: already sent for this campaign/round"

    if _dry_run():
        result = f"DRY_RUN: would post to r/{subreddit}: {title!r}"
    else:
        result = post_to_reddit(subreddit, title, body)

    mark_sent(campaign_id, round_id, channel, result)
    return result


def send_campaign_email(
    campaign_id: str,
    round_id: int,
    to: list[str],
    subject: str,
    html: str,
    *,
    cta_url: str | None = None,
) -> str:
    channel = "email"
    if already_sent(campaign_id, round_id, channel):
        return "skipped: already sent for this campaign/round"

    if cta_url:
        link = (
            wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel)
            if os.environ.get("TRACK_CLICK_BASE_URL")
            else cta_url
        )
        html = f'{html}<p><a href="{link}">Learn more</a></p>'

    if _dry_run():
        result = f"DRY_RUN: would email {to}: {subject!r}"
    else:
        result = send_email(to, subject, html)

    mark_sent(campaign_id, round_id, channel, result)
    return result
