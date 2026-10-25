import base64
import hashlib
import html as html_lib
import logging
import os
import time

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
    """One email per recipient (nobody sees the other addresses), each with its
    own idempotency key, under one ledger row per campaign/round/channel."""
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

    recipients = [{"to": a, "unit_hash": recipient_key(a)} for a in dict.fromkeys(x.strip() for x in to if x and x.strip())]
    payload = {"experiment_id": None, "per_recipient": recipients, "subject": subject, "html": html, "cta_url": None}
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    return deliver(
        channel,
        campaign_id,
        round_id,
        payload,
        lambda: _send_each(campaign_id, round_id, channel, payload, image_bytes),
        describe=f"would email {len(recipients)} recipient(s) one by one: {subject!r}",
        user_id=user_id,
    )


def recipient_key(address: str) -> str:
    """A stable per-recipient id for idempotency keys (the address itself stays out of them)."""
    return hashlib.sha256(address.strip().lower().encode()).hexdigest()


# Where each recipient's own link goes in an experiment email's html.
LINK_SLOT = "__CIQ_LINK__"


def personal_link(cta_url: str, *, campaign_id: str, round_id: int, channel: str, token: str) -> str:
    """The recipient's link: tracked (the click is credited to their unit) and,
    either way, carrying their token to the brand's site for conversions."""
    if os.environ.get("TRACK_CLICK_BASE_URL"):
        return wrap_tracked_url(cta_url, campaign_id=campaign_id, round_id=round_id, channel=channel, token=token)
    return with_token(cta_url, token)


def send_experiment_email(
    campaign_id: str,
    round_id: int,
    recipients: list[dict],
    subject: str,
    html: str,
    *,
    experiment_id: str,
    cta_url: str | None = None,
    user_id: str | None = None,
    channel: str = "email",
    image_bytes: bytes | None = None,
    image_alt: str = "",
) -> str:
    """An experiment's emails: one per recipient (`recipients`: {to, token,
    unit_hash}), like every campaign email, plus each link carries that
    person's token. Same ledger row as a normal send (at most once per
    campaign/round/channel); each email has its own idempotency key, so a retry
    after a partial failure never emails anyone twice."""
    if cta_url:
        html = f'{html}<p><a href="{LINK_SLOT}">Learn more</a></p>'
    if image_bytes:
        html = with_ad_image(html, image_alt, LINK_SLOT if cta_url else None)
    payload = {"experiment_id": experiment_id, "per_recipient": recipients, "subject": subject, "html": html, "cta_url": cta_url}
    if image_bytes:
        payload["image_base64"] = base64.b64encode(image_bytes).decode()
    return deliver(
        channel, campaign_id, round_id, payload,
        lambda: _send_each(campaign_id, round_id, channel, payload, image_bytes),
        describe=f"would email {len(recipients)} recipient(s) one by one: {subject!r}", user_id=user_id,
    )


def _send_each(campaign_id: str, round_id: int, channel: str, payload: dict, image_bytes: bytes | None) -> str:
    from src.capabilities.impact import SEND_PACING_SECONDS, record_exposures

    sent, first_id = [], None
    try:
        for i, r in enumerate(payload["per_recipient"]):
            if i:
                time.sleep(SEND_PACING_SECONDS)
            body = payload["html"]
            if payload.get("cta_url") and r.get("token"):
                link = personal_link(payload["cta_url"], campaign_id=campaign_id, round_id=round_id, channel=channel, token=r["token"])
                body = body.replace(LINK_SLOT, html_lib.escape(link, quote=True))
            email_id = send_email([r["to"]], payload["subject"], body, image_bytes=image_bytes,
                                  idempotency_key=f"{campaign_id}:{round_id}:{channel}:{r['unit_hash'][:32]}")
            first_id = first_id or email_id
            sent.append(r["unit_hash"])
    finally:
        if sent and payload.get("experiment_id"):  # whatever went out is an exposure, even if a later send failed
            record_exposures(payload["experiment_id"], round_id, sent)
    return f"{len(sent)} emails ({first_id})"


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
        image = base64.b64decode(payload["image_base64"]) if payload.get("image_base64") else None
        return deliver(
            channel, campaign_id, round_id, payload, lambda: _send_each(campaign_id, round_id, channel, payload, image),
            describe=f"would email {len(payload['per_recipient'])} recipient(s) one by one", user_id=user_id,
        )
    if channel in ("email", "email_b"):
        # The stored html already carries the (tracked) CTA link and the
        # image tag; only the image bytes go back in as the attachment.
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
