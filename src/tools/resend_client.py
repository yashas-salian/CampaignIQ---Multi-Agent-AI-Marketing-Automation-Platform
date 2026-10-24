import base64
import os

import resend

# The finished ad travels inside the email as an inline attachment, referenced
# as <img src="cid:ad-image">: no public link to host, nothing that expires.
AD_IMAGE_CID = "ad-image"


def send_email(to: list[str], subject: str, html: str, image_bytes: bytes | None = None) -> str:
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
    result = resend.Emails.send(params)
    return result["id"]
