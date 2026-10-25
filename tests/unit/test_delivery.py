import json

import pytest

from src.capabilities import delivery, distribution
from src.capabilities.metrics import _is_real_post_ref


class Flaky:
    """A send function that fails `failures` times, then succeeds."""

    def __init__(self, failures: int, result: str = "at://post/1"):
        self.failures, self.result, self.calls = failures, result, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("bluesky timeout")
        return self.result


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "false")


def send(fn, round_id=1):
    return delivery.deliver("bluesky", "c1", round_id, {"copy_text": "hi"}, fn, describe="would post", user_id="u1")


def test_dry_run_is_recorded_and_not_resent():
    assert send(lambda: pytest.fail("real send in DRY_RUN")) == "DRY_RUN: would post"
    assert send(lambda: pytest.fail("resent")) == delivery.SKIPPED


def test_transient_failures_are_retried_in_process(live):
    flaky = Flaky(failures=2)
    assert send(flaky) == "at://post/1" and flaky.calls == 3
    assert send(Flaky(0, "at://post/2")) == delivery.SKIPPED  # exactly once


def test_persistent_failure_is_scheduled_for_retry_not_raised(live, delivery_ledger):
    result = send(Flaky(failures=99))
    assert result.startswith("failed: ConnectionError: bluesky timeout (retry scheduled")
    row = json.loads(delivery_ledger.read_text())["c1:1:bluesky"]
    assert row["status"] == "failed" and row["attempts"] == 1 and row["next_attempt_at"]
    assert row["payload"] == {"copy_text": "hi"}


def test_retry_after_failure_can_succeed(live):
    send(Flaky(failures=99))
    assert send(Flaky(failures=0, result="at://post/9")) == "at://post/9"


def test_gives_up_after_max_attempts_and_alerts(live, monkeypatch):
    alerts = []
    monkeypatch.setattr(delivery, "_alert_dead", lambda *a: alerts.append(a))
    results = [send(Flaky(failures=99)) for _ in range(delivery.MAX_ATTEMPTS)]
    assert all(r.startswith("failed:") for r in results[:-1])
    assert results[-1].startswith(f"dead: gave up after {delivery.MAX_ATTEMPTS} attempts")
    assert len(alerts) == 1
    assert send(lambda: pytest.fail("dead letters are not resent automatically")).startswith("dead:")


def test_no_ledger_means_no_send(monkeypatch, live):
    monkeypatch.setattr(delivery, "ledger", lambda: (_ for _ in ()).throw(ConnectionError("db down")))
    assert send(lambda: pytest.fail("sent without a ledger claim")).startswith("failed: delivery ledger unavailable")


def test_a_dropped_ledger_connection_is_retried(monkeypatch, live):
    # Seen in production: one "Server disconnected" lost a round's email.
    real, calls = delivery.ledger, []

    def flaky_ledger():
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("Server disconnected")
        return real()

    monkeypatch.setattr(delivery, "ledger", flaky_ledger)
    assert send(Flaky(failures=0)) == "at://post/1"
    assert len(calls) == 2


def test_backoff_grows():
    assert delivery.RETRY_BACKOFF_MINUTES == tuple(sorted(delivery.RETRY_BACKOFF_MINUTES))


def test_failed_and_dead_refs_are_not_collected_as_posts():
    assert not _is_real_post_ref("failed: ConnectionError (retry scheduled ...)")
    assert not _is_real_post_ref("dead: gave up after 5 attempts")
    assert _is_real_post_ref("at://did:plc:x/app.bsky.feed.post/1")


def test_stored_payload_replays_the_same_send(live, monkeypatch):
    sent = []
    monkeypatch.setattr(distribution, "send_email", lambda to, subject, html, **_: sent.append((to, subject, html)) or "em_1")
    payload = {"to": ["a@x.io"], "subject": "Hi", "html": "<p>x</p><p><a href='t'>Learn more</a></p>"}
    assert distribution.resend_from_payload("email", "c9", 3, payload, "u1") == "em_1"
    assert sent == [(["a@x.io"], "Hi", payload["html"])]  # CTA link not appended twice


class Ambiguous:
    """A send that reaches the provider and then times out the first time."""

    def __init__(self):
        self.posted, self.calls = [], 0

    def __call__(self):
        self.calls += 1
        self.posted.append("at://post/1")
        if self.calls == 1:
            raise TimeoutError("read timed out after the post was accepted")
        return "at://post/1"

    def reconcile(self):
        return self.posted[0] if self.posted else None


def send_with(fn, reconcile, round_id=1):
    return delivery.deliver("bluesky", "c1", round_id, {"copy_text": "hi"}, fn, describe="would post",
                            user_id="u1", reconcile=reconcile)


def test_a_timed_out_send_that_went_out_is_not_posted_again(live):
    post = Ambiguous()
    assert send_with(post, post.reconcile) == "at://post/1"
    assert post.calls == 1  # the retry found the first post instead of posting twice


def test_a_send_that_failed_before_reaching_the_provider_is_retried(live):
    flaky = Flaky(failures=1)
    assert send_with(flaky, lambda: None) == "at://post/1" and flaky.calls == 2


def test_when_the_outcome_is_unknown_nothing_is_resent(live, delivery_ledger):
    flaky = Flaky(failures=1)

    def cannot_tell():
        raise ConnectionError("feed unavailable")

    result = send_with(flaky, cannot_tell)
    assert flaky.calls == 1 and result.startswith("failed: outcome of an earlier attempt unknown")
    assert json.loads(delivery_ledger.read_text())["c1:1:bluesky"]["status"] == "failed"


def test_a_scheduled_retry_reconciles_first(live):
    send(Flaky(failures=99))  # attempt 1 fails (maybe after reaching Bluesky)
    assert send_with(lambda: pytest.fail("posted again"), lambda: "at://post/found") == "at://post/found"


def test_emails_carry_an_idempotency_key(live, monkeypatch):
    seen = {}
    monkeypatch.setattr(distribution, "send_email", lambda *a, **k: seen.update(k) or "em_1")
    distribution.send_campaign_email("c7", 2, ["a@x.io"], "Hi", "<p>x</p>", user_id="u1")
    assert seen["idempotency_key"] == "c7:2:email:" + distribution.recipient_key("a@x.io")[:32]  # one key per recipient
