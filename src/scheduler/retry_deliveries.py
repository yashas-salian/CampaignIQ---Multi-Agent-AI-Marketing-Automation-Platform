"""Retry failed channel deliveries whose backoff has elapsed.

Runs from the hourly campaign-loop sweep. A delivery that keeps failing ends in
the 'dead' state (the dead-letter queue) after MAX_ATTEMPTS, with an ops alert;
see src/capabilities/delivery.py.
"""
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.capabilities.delivery import is_failure
from src.capabilities.distribution import resend_from_payload
from src.db.supabase_client import get_client, upsert_iteration

ITERATION_COLUMN = {
    "bluesky": "bluesky_post_uri", "mastodon": "mastodon_post_url", "reddit": "reddit_post_url",
    "email": "email_id", "email_b": "email_id_b",
}
BATCH = 50


def retry_due() -> dict[str, int]:
    due = (
        get_client()
        .table("deliveries")
        .select("campaign_id,round_number,channel,payload,user_id")
        .eq("status", "failed")
        .lte("next_attempt_at", datetime.now(timezone.utc).isoformat())
        .order("next_attempt_at")
        .limit(BATCH)
        .execute()
        .data
    )
    counts = {"sent": 0, "failed": 0}
    for row in due:
        ref = resend_from_payload(row["channel"], row["campaign_id"], row["round_number"], row["payload"], row["user_id"])
        counts["failed" if is_failure(ref) else "sent"] += 1
        if not is_failure(ref) and row["user_id"] and not row["campaign_id"].startswith("mcp-"):
            # Point the round at the real post/email so metrics collection finds it.
            upsert_iteration(row["campaign_id"], row["user_id"], row["round_number"], **{ITERATION_COLUMN[row["channel"]]: ref})
        print(f"{row['channel']} {row['campaign_id']} round {row['round_number']}: {ref[:120]}")
    return counts


def main() -> None:
    load_dotenv()
    counts = retry_due()
    print(f"Delivery retries: {counts['sent']} sent, {counts['failed']} still failing.")


if __name__ == "__main__":
    main()
