import base64
import hashlib
import html as html_lib
import logging
import os

from src.capabilities.delivery import deliver
from src.tools.bluesky_client import find_own_post, post_to_bluesky
from src.tools.mastodon_client import post_to_mastodon
from src.tools.reddit_client import post_to_reddit
from src.tools.resend_client import AD_IMAGE_CID, send_email
from src.tools.track_click import with_token, wrap_tracked_url

logger = logging.getLogger("capabilities.distribution")

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
        reconcile=lambda: find_own_post(copy_text),
    )


def post_mastodon(
    campaign_id: str, round_id: int, copy_text: str, image_bytes: bytes | None = None, *, image_alt: str = "",
    user_id: str | None = None,
) -> str:
    payload = {
        "copy_text": copy_text,
        "image_alt": image_alt,
        "image_base64": base64.b64encode(image_bytes).decode() if image_bytes else None,
    }
    return deliver(
        "mastodon",
        campaign_id,
        round_id,
        payload,
        lambda: post_to_mastodon(
            copy_text, image_bytes=image_bytes, image_alt=image_alt, idempotency_key=f"{campaign_id}:{round_id}"
        ),
        describe=f"would post to Mastodon: {copy_text[:60]!r}",
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


def tracked_link(cta_url: str, *, campaign_id: str, round_id: int, channel: str) -> str:
    """The CTA as a click-tracked link when tracking is configured, else as is."""
    if os.environ.get("TRACK_CLICK_BASE_URL"):
        return wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel)
    return cta_url


def recipient_key(address: str) -> str:
    """A stable per-recipient id for idempotency keys (the address itself stays out of them)."""
    return hashlib.sha256(address.strip().lower().encode()).hexdigest()


# Where each recipient's own link goes in an experiment email's html.
LINK_SLOT = "__CIQ_LINK__"


def personal_link(cta_url: str, *, campaign_id: str, round_id: int, channel: str, token: str | None = None,
                  contact_token: str | None = None) -> str:
    """The recipient's link: tracked (the click is credited to their experiment
    unit and marks the contact engaged) and, either way, carrying their
    experiment token to the brand's site for conversions."""
    if os.environ.get("TRACK_CLICK_BASE_URL"):
        return wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel, token=token,
                                contact_token=contact_token)
    return with_token(cta_url, token) if token else cta_url


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
    if channel == "mastodon":
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return post_mastodon(
            campaign_id, round_id, payload["copy_text"], image, image_alt=payload.get("image_alt", ""), user_id=user_id
        )
    if channel == "reddit":
        return post_reddit(campaign_id, round_id, payload["subreddit"], payload["title"], payload["body"], user_id=user_id)
    if channel in ("email", "email_b") and payload.get("per_recipient"):
        from src.capabilities.email_engine import send_payload

        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return deliver(
            channel, campaign_id, round_id, payload, lambda: send_payload(campaign_id, round_id, channel, payload, image),
            describe=f"would email {len(payload['per_recipient'])} recipient(s) one by one", user_id=user_id,
        )
    if channel in ("email", "email_b"):
        # A legacy single batched send: the stored html already carries the
        # (tracked) CTA link and the image tag; the image goes back as the attachment.
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return deliver(
            channel, campaign_id, round_id, payload,
            lambda: send_email(
                payload["to"], payload["subject"], payload["html"], image_bytes=image,
                idempotency_key=f"{campaign_id}:{round_id}:{channel}",
            ),
            describe=f"would email {payload['to']}: {payload['subject']!r}", user_id=user_id,
        )
    raise ValueError(f"unknown channel {channel}")
