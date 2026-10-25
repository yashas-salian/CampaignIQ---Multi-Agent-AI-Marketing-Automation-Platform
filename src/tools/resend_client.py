import base64
import os

import resend

# The finished ad travels inside the email as an inline attachment, referenced
# as <img src="cid:ad-image">: no public link to host, nothing that expires.
AD_IMAGE_CID = "ad-image"


def send_email(
    to: list[str], subject: str, html: str, image_bytes: bytes | None = None, *, idempotency_key: str | None = None
) -> str:
    resend.api_key = os.environ["RESEND_API_KEY"]
    params = {
        "from": os.environ["RESEND_FROM_EMAIL"],
        "to": to,
        "subject": subject,
        "html": html,
    }
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
