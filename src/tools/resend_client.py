import base64
import os

import resend

# The finished ad travels inside the email as an inline attachment, referenced
# as <img src="cid:ad-image">: no public link to host, nothing that expires.
AD_IMAGE_CID = "ad-image"


def send_email(
    to: list[str], subject: str, html: str, image_bytes: bytes | None = None, *, idempotency_key: str | None = None,
    sender: dict | None = None, headers: dict | None = None,
) -> str:
    """Send one email. `sender` ({api_key, from, reply_to}) is an organisation's
    own Resend account; without it, the app's own (RESEND_API_KEY /
    RESEND_FROM_EMAIL: notifications, alerts and the test inbox)."""
    resend.api_key = sender["api_key"] if sender else os.environ["RESEND_API_KEY"]
    params = {
        "from": sender["from"] if sender else os.environ["RESEND_FROM_EMAIL"],
        "to": to,
        "subject": subject,
        "html": html,
    }
    if sender and sender.get("reply_to"):
        params["reply_to"] = sender["reply_to"]
    if headers:
        params["headers"] = headers
    if image_bytes:
        params["attachments"] = [
            {
                "filename": "ad.jpg",
                "content": base64.b64encode(image_bytes).decode(),
                "content_type": "image/jpeg",
                "content_id": AD_IMAGE_CID,
            }
        ]
    # With a key, Resend answers a repeat of the same request (a retry after a
    # timeout) with the first email instead of sending it again.
    result = resend.Emails.send(params, {"idempotency_key": idempotency_key}) if idempotency_key else resend.Emails.send(params)
    return result["id"]
