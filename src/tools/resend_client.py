import os

import resend


def send_email(to: list[str], subject: str, html: str) -> str:
    resend.api_key = os.environ["RESEND_API_KEY"]
    result = resend.Emails.send(
        {
            "from": os.environ["RESEND_FROM_EMAIL"],
            "to": to,
            "subject": subject,
            "html": html,
        }
    )
    return result["id"]
