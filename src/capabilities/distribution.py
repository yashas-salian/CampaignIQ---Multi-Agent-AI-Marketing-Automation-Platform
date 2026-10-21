import base64
import os

from src.capabilities.delivery import deliver
from src.tools.bluesky_client import post_to_bluesky
from src.tools.reddit_client import post_to_reddit
from src.tools.resend_client import send_email
from src.tools.track_click import wrap_tracked_url

# Each channel send goes through deliver(): at most once per campaign/round,
# DRY_RUN-aware, retried on failure and never raising into the graph. The
# payload is stored in the delivery ledger so a failed send can be retried
# later by src.scheduler.retry_deliveries without re-running the campaign.


def post_bluesky(
    campaign_id: str, round_id: int, copy_text: str, image_bytes: bytes | None = None, *, user_id: str | None = None
) -> str:
    payload = {"copy_text": copy_text, "image_base64": base64.b64encode(image_bytes).decode() if image_bytes else None}
    return deliver(
        "bluesky",
        campaign_id,
        round_id,
        payload,
        lambda: post_to_bluesky(copy_text, image_bytes=image_bytes),
        describe=f"would post to Bluesky: {copy_text[:60]!r}",
        user_id=user_id,
    )


def post_reddit(
    campaign_id: str, round_id: int, subreddit: str, title: str, body: str, *, user_id: str | None = None
) -> str:
    return deliver(
        "reddit",
        campaign_id,
        round_id,
        {"subreddit": subreddit, "title": title, "body": body},
        lambda: post_to_reddit(subreddit, title, body),
        describe=f"would post to r/{subreddit}: {title!r}",
        user_id=user_id,
    )


def send_campaign_email(
    campaign_id: str,
    round_id: int,
    to: list[str],
    subject: str,
    html: str,
    *,
    cta_url: str | None = None,
    user_id: str | None = None,
) -> str:
    if cta_url:
        link = (
            wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel="email")
            if os.environ.get("TRACK_CLICK_BASE_URL")
            else cta_url
        )
        html = f'{html}<p><a href="{link}">Learn more</a></p>'

    return deliver(
        "email",
        campaign_id,
        round_id,
        {"to": to, "subject": subject, "html": html},
        lambda: send_email(to, subject, html),
        describe=f"would email {to}: {subject!r}",
        user_id=user_id,
    )


def resend_from_payload(channel: str, campaign_id: str, round_id: int, payload: dict, user_id: str | None) -> str:
    """Retry a stored delivery (used by the retry scheduler)."""
    if channel == "bluesky":
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return post_bluesky(campaign_id, round_id, payload["copy_text"], image, user_id=user_id)
    if channel == "reddit":
        return post_reddit(campaign_id, round_id, payload["subreddit"], payload["title"], payload["body"], user_id=user_id)
    if channel == "email":
        # The stored html already carries the (tracked) CTA link.
        return send_campaign_email(campaign_id, round_id, payload["to"], payload["subject"], payload["html"], user_id=user_id)
    raise ValueError(f"unknown channel {channel}")
