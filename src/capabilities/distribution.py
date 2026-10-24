import base64
import html as html_lib
import os

from src.capabilities.delivery import deliver
from src.tools.bluesky_client import post_to_bluesky
from src.tools.reddit_client import post_to_reddit
from src.tools.resend_client import AD_IMAGE_CID, send_email
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
    channel: str = "email",  # "email_b" for an A/B test's variant B
    image_bytes: bytes | None = None,
    image_alt: str = "",
) -> str:
    link = None
    if cta_url:
        link = (
            wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel)
            if os.environ.get("TRACK_CLICK_BASE_URL")
            else cta_url
        )
        html = f'{html}<p><a href="{link}">Learn more</a></p>'
    if image_bytes:
        html = with_ad_image(html, image_alt, link)

    payload = {"to": to, "subject": subject, "html": html}
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    return deliver(
        channel,
        campaign_id,
        round_id,
        payload,
        lambda: send_email(to, subject, html, image_bytes=image_bytes),
        describe=f"would email {to}: {subject!r}",
        user_id=user_id,
    )


def with_ad_image(html: str, alt: str, link: str | None) -> str:
    """Put the finished ad in the email: where a template has an {{image}}
    placeholder, else on top. Clicking it follows the CTA link, if any."""
    img = (
        f'<img src="cid:{AD_IMAGE_CID}" alt="{html_lib.escape(alt, quote=True)}" width="480" '
        'style="display:block;width:100%;max-width:480px;height:auto;border:0;border-radius:8px">'
    )
    if link:
        img = f'<a href="{link}">{img}</a>'
    if "{{image}}" in html:
        return html.replace("{{image}}", img)
    return f"<p>{img}</p>{html}"


def resend_from_payload(channel: str, campaign_id: str, round_id: int, payload: dict, user_id: str | None) -> str:
    """Retry a stored delivery (used by the retry scheduler)."""
    if channel == "bluesky":
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return post_bluesky(campaign_id, round_id, payload["copy_text"], image, user_id=user_id)
    if channel == "reddit":
        return post_reddit(campaign_id, round_id, payload["subreddit"], payload["title"], payload["body"], user_id=user_id)
    if channel in ("email", "email_b"):
        # The stored html already carries the (tracked) CTA link and the
        # image tag; only the image bytes go back in as the attachment.
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return deliver(
            channel, campaign_id, round_id, payload,
            lambda: send_email(payload["to"], payload["subject"], payload["html"], image_bytes=image),
            describe=f"would email {payload['to']}: {payload['subject']!r}", user_id=user_id,
        )
    raise ValueError(f"unknown channel {channel}")
