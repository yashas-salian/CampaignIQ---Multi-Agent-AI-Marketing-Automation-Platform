"""Webhook sweep: confirm first attempts, retry failures, give up eventually.

The database sends each event's first attempt itself (pg_net, from the
audit-log trigger). This sweep, run with the hourly loop:
  1. reads pg_net's responses: 2xx -> sent; anything else -> scheduled retry;
  2. re-sends due retries directly (same HMAC signature), with backoff;
  3. marks a delivery failed after MAX_ATTEMPTS.
Receivers should verify `X-CampaignIQ-Signature: sha256=<hex>` =
HMAC-SHA256(secret, raw body) and de-duplicate on `X-CampaignIQ-Delivery`.
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

logger = logging.getLogger("scheduler.webhooks")

MAX_ATTEMPTS = 6
BACKOFF_MINUTES = (1, 5, 30, 120, 480)  # before attempts 2..6
STUCK_AFTER = timedelta(minutes=15)    # an attempt with no response by now counts as failed


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _schedule_retry(client, delivery: dict, response_status: int | None) -> str:
    attempts = delivery["attempts"]
    if attempts >= MAX_ATTEMPTS:
        client.table("webhook_deliveries").update(
            {"status": "failed", "response_status": response_status, "updated_at": _now().isoformat()}
        ).eq("id", delivery["id"]).execute()
        return "failed"
    wait = BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1]
    client.table("webhook_deliveries").update(
        {"next_attempt_at": (_now() + timedelta(minutes=wait)).isoformat(), "response_status": response_status,
         "net_request_id": None, "updated_at": _now().isoformat()}
    ).eq("id", delivery["id"]).execute()
    return "retry"


def sweep() -> dict[str, int]:
    from src.db.supabase_client import get_client

    client = get_client()
    counts = {"sent": 0, "retry": 0, "failed": 0}

    # 1. Outcomes of the database's own attempts.
    for r in client.rpc("webhook_responses").execute().data or []:
        delivery = client.table("webhook_deliveries").select("*").eq("id", r["delivery_id"]).single().execute().data
        if r["status_code"] and 200 <= r["status_code"] < 300:
            client.table("webhook_deliveries").update(
                {"status": "sent", "response_status": r["status_code"], "updated_at": _now().isoformat()}
            ).eq("id", delivery["id"]).execute()
            counts["sent"] += 1
        else:
            counts[_schedule_retry(client, delivery, r["status_code"])] += 1

    # Attempts that never got a response (pg_net down, response row expired).
    stuck = (
        client.table("webhook_deliveries").select("*").eq("status", "pending").not_.is_("net_request_id", "null")
        .lt("updated_at", (_now() - STUCK_AFTER).isoformat()).execute().data
    )
    for delivery in stuck:
        counts[_schedule_retry(client, delivery, None)] += 1

    # 2. Due retries, sent from here.
    due = (
        client.table("webhook_deliveries").select("*, webhooks(url, secret, active)").eq("status", "pending")
        .is_("net_request_id", "null").lte("next_attempt_at", _now().isoformat()).limit(100).execute().data
    )
    for delivery in due:
        hook = delivery.get("webhooks") or {}
        if not hook.get("active"):
            continue
        body = json.dumps(delivery["payload"], separators=(",", ":")).encode()
        attempt = delivery["attempts"] + 1
        delivery = {**delivery, "attempts": attempt}
        client.table("webhook_deliveries").update({"attempts": attempt}).eq("id", delivery["id"]).execute()
        try:
            response = requests.post(
                hook["url"], data=body, timeout=10,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "CampaignIQ-Webhooks/1",
                    "X-CampaignIQ-Event": delivery["event"],
                    "X-CampaignIQ-Delivery": str(delivery["id"]),
                    "X-CampaignIQ-Signature": sign(hook["secret"], body),
                    # The old names too, while existing receivers move over.
                    "X-MarketingOS-Event": delivery["event"],
                    "X-MarketingOS-Delivery": str(delivery["id"]),
                    "X-MarketingOS-Signature": sign(hook["secret"], body),
                },
            )
            status = response.status_code
        except requests.RequestException as exc:
            logger.warning("webhook %s attempt %s failed: %s", delivery["id"], attempt, exc)
            status = None
        if status and 200 <= status < 300:
            client.table("webhook_deliveries").update(
                {"status": "sent", "response_status": status, "updated_at": _now().isoformat()}
            ).eq("id", delivery["id"]).execute()
            counts["sent"] += 1
        else:
            counts[_schedule_retry(client, delivery, status)] += 1
    return counts


def main() -> None:
    load_dotenv()
    print("Webhooks:", sweep())


if __name__ == "__main__":
    main()
