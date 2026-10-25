"""Reliable, exactly-once-per-round delivery for the distribution channels.

Every send goes through `deliver()`:
  1. claim (campaign, round, channel) in the ledger -- if it was already sent,
     or another worker is sending it right now, nothing is sent again;
  2. try the send a few times in-process for transient errors;
  3. record the outcome: sent / dry_run, or failed with a retry time (picked up
     by `src.scheduler.retry_deliveries`), or dead after MAX_ATTEMPTS, which
     raises an ops alert.
A send never raises into the graph: a channel outage is recorded and retried,
it doesn't crash the campaign run.

Ledger: the `deliveries` table (service role) wherever Supabase is configured,
so dedup survives across GitHub Actions runs. Without Supabase credentials
(local scripts, unit tests) a local JSON file is used instead; set
DELIVERY_LEDGER=db|file to force one.
"""
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger("capabilities.delivery")

MAX_ATTEMPTS = 5
IN_PROCESS_TRIES = 3
IN_PROCESS_BACKOFF = (1.0, 3.0)  # seconds between the in-process tries
RETRY_BACKOFF_MINUTES = (5, 30, 120, 480)  # before attempts 2, 3, 4, 5
SKIPPED = "skipped: already sent for this campaign/round"


class LedgerUnavailable(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").lower() == "true"


def is_failure(ref: str | None) -> bool:
    return bool(ref) and ref.startswith(("failed:", "dead:"))


# --- Ledgers -----------------------------------------------------------------


class DbLedger:
    """The `deliveries` table. The claim is the SQL function claim_delivery():
    insert-or-lock in one transaction, so concurrent workers can't both win."""

    def __init__(self):
        from src.db.supabase_client import get_client

        self._client = get_client()

    def claim(self, campaign_id: str, round_id: int, channel: str, user_id: str | None, payload: dict):
        """Returns ("go", row_id) or ("done", message)."""
        row = (
            self._client.rpc(
                "claim_delivery",
                {"p_campaign_id": campaign_id, "p_round": round_id, "p_channel": channel,
                 "p_user_id": user_id, "p_payload": payload},
            )
            .execute()
            .data[0]
        )
        self._attempts = {row["delivery_id"]: row["attempts"]}
        return ("go", row["delivery_id"]) if row["verdict"] == "go" else ("done", row["note"])

    def finish(self, row_id: str, *, status: str, result_ref: str | None = None, error: str | None = None,
               next_attempt_at: datetime | None = None) -> None:
        self._client.table("deliveries").update(
            {
                "status": status,
                "result_ref": result_ref,
                "last_error": error,
                "next_attempt_at": next_attempt_at.isoformat() if next_attempt_at else None,
                "updated_at": _now().isoformat(),
            }
        ).eq("id", row_id).execute()

    def attempts(self, row_id: str) -> int:
        return self._attempts[row_id]


class FileLedger:
    """Local single-process stand-in (no Supabase): same states, one JSON file."""

    def __init__(self, path: Path | None = None):
        self.path = path or Path(os.environ.get("DEDUP_STORE_PATH", ".local_dedup_store.json"))

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))

    def claim(self, campaign_id, round_id, channel, user_id, payload):
        key = f"{campaign_id}:{round_id}:{channel}"
        data = self._load()
        row = data.get(key) or {"attempts": 0, "status": "pending"}
        if not isinstance(row, dict):  # legacy entry: {key: result}
            return "done", SKIPPED
        if row["status"] in ("sent", "dry_run"):
            return "done", SKIPPED
        if row["status"] == "dead":
            return "done", f"dead: gave up after {row['attempts']} attempts ({row.get('last_error')})"
        row.update(status="sending", attempts=row["attempts"] + 1, payload=payload)
        data[key] = row
        self._save(data)
        return "go", key

    def finish(self, row_id, *, status, result_ref=None, error=None, next_attempt_at=None):
        data = self._load()
        data[row_id].update(status=status, result_ref=result_ref, last_error=error,
                            next_attempt_at=next_attempt_at.isoformat() if next_attempt_at else None)
        self._save(data)

    def attempts(self, row_id) -> int:
        return self._load()[row_id]["attempts"]


def ledger():
    choice = os.environ.get("DELIVERY_LEDGER", "").lower()
    if choice == "file" or (choice != "db" and not os.environ.get("SUPABASE_SERVICE_ROLE_KEY")):
        return FileLedger()
    try:
        return DbLedger()
    except Exception as exc:
        raise LedgerUnavailable(str(exc)) from exc


# --- Delivery ----------------------------------------------------------------


def _alert_dead(channel: str, campaign_id: str, round_id: int, error: str) -> None:
    logger.error("DELIVERY DEAD: %s campaign=%s round=%s: %s", channel, campaign_id, round_id, error)
    to = os.environ.get("OPS_ALERT_EMAIL")
    if not to or _dry_run():
        return
    try:
        from src.tools.resend_client import send_email

        send_email(
            [to],
            f"[MarketingOS] {channel} delivery gave up (campaign {campaign_id}, round {round_id})",
            f"<p>After {MAX_ATTEMPTS} attempts the {channel} send for campaign <code>{campaign_id}</code> "
            f"round {round_id} was moved to the dead-letter queue.</p><p>Last error: <code>{error}</code></p>",
        )
    except Exception as exc:
        logger.error("ops alert email failed: %s", exc)


def deliver(
    channel: str,
    campaign_id: str,
    round_id: int,
    payload: dict,
    send: Callable[[], str],
    *,
    describe: str,
    user_id: str | None = None,
    reconcile: Callable[[], str | None] | None = None,
) -> str:
    """Send at most once per (campaign, round, channel). Returns the result
    reference, a "DRY_RUN: ..." / "skipped: ..." note, or "failed: ..." /
    "dead: ..." -- never raises.

    A send that times out may still have reached the provider. Channels
    without an idempotency key pass `reconcile`: before any repeat attempt
    (in-process or scheduled) it looks for the earlier post and returns its
    reference, or None if it really didn't go out. If it can't tell (it
    raises), nothing is sent this time: the attempt is rescheduled rather
    than risking a duplicate."""
    # A dropped connection ("Server disconnected") is usually transient, so the
    # claim is retried too. claim_delivery() locks the row: a retry can't double-send.
    for attempt in range(IN_PROCESS_TRIES):
        try:
            book = ledger()
            verdict, row = book.claim(campaign_id, round_id, channel, user_id, payload)
            break
        except Exception as exc:
            if attempt < IN_PROCESS_TRIES - 1:
                logger.warning("%s ledger claim attempt %d failed: %s", channel, attempt + 1, exc)
                time.sleep(IN_PROCESS_BACKOFF[attempt])
                continue
            # Without a ledger claim we can't know it wasn't already sent: don't send.
            logger.error("%s delivery for %s/%s not attempted, ledger unavailable: %s", channel, campaign_id, round_id, exc)
            return f"failed: delivery ledger unavailable ({exc})"
    if verdict == "done":
        return row

    if _dry_run():
        result = f"DRY_RUN: {describe}"
        book.finish(row, status="dry_run", result_ref=result)
        return result

    error = ""
    for attempt in range(IN_PROCESS_TRIES):
        if reconcile and (attempt > 0 or book.attempts(row) > 1):
            try:
                found = reconcile()
            except Exception as exc:
                error = f"outcome of an earlier attempt unknown, not resending: {type(exc).__name__}: {str(exc)[:200]}"
                logger.warning("%s reconcile failed: %s", channel, error)
                break
            if found:
                logger.info("%s: an earlier attempt did go out (%s); not resending", channel, found)
                book.finish(row, status="sent", result_ref=found)
                return found
        try:
            result = send()
        except Exception as exc:
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
            logger.warning("%s send attempt %d failed: %s", channel, attempt + 1, error)
            if attempt < IN_PROCESS_TRIES - 1:
                time.sleep(IN_PROCESS_BACKOFF[attempt])
            continue
        book.finish(row, status="sent", result_ref=result)
        return result

    attempts = book.attempts(row)
    if attempts >= MAX_ATTEMPTS:
        book.finish(row, status="dead", error=error)
        _alert_dead(channel, campaign_id, round_id, error)
        return f"dead: gave up after {attempts} attempts ({error})"
    retry_at = _now() + timedelta(minutes=RETRY_BACKOFF_MINUTES[min(attempts, len(RETRY_BACKOFF_MINUTES)) - 1])
    book.finish(row, status="failed", error=error, next_attempt_at=retry_at)
    return f"failed: {error} (retry scheduled {retry_at:%Y-%m-%d %H:%M} UTC)"
