import hashlib
import hmac

from src.scheduler import webhooks


class Table:
    def __init__(self, log):
        self.log = log

    def update(self, row):
        self.log.append(row)
        return self

    def eq(self, *a):
        return self

    def execute(self):
        return None


class Client:
    def __init__(self):
        self.updates = []

    def table(self, name):
        return Table(self.updates)


def test_signature_is_hmac_sha256_of_the_raw_body():
    body = b'{"event":"ping"}'
    assert webhooks.sign("s3cret", body) == "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()


def test_failures_back_off_then_give_up():
    client = Client()
    assert webhooks._schedule_retry(client, {"id": 1, "attempts": 1}, 500) == "retry"
    assert client.updates[-1]["net_request_id"] is None and client.updates[-1]["response_status"] == 500
    assert webhooks._schedule_retry(client, {"id": 1, "attempts": webhooks.MAX_ATTEMPTS}, 502) == "failed"
    assert client.updates[-1]["status"] == "failed"


def test_backoff_grows():
    assert list(webhooks.BACKOFF_MINUTES) == sorted(webhooks.BACKOFF_MINUTES)
