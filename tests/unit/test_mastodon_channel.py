"""Mastodon as a posting channel: the client (faked HTTP), delivery, the graph
node, guardrails, metrics and the bandit context. No network."""
import base64
import json

import numpy as np
import pytest

from src.capabilities import distribution, guardrails
from src.capabilities.creative import Creative
from src.constants import active_channels
from src.graph import build_graph as graph
from src.graph.nodes import distribution_mastodon as node
from src.scheduler.retry_deliveries import ITERATION_COLUMN
from src.tools import bandit, mastodon_client

POST_URL = "https://mastodon.social/@brewline/113456789"


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


@pytest.fixture
def posting(monkeypatch):
    monkeypatch.setenv("MASTODON_POST_TOKEN", "test-post-token")


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def post(url, headers=None, data=None, files=None, timeout=None):
        calls.append(("POST", url, headers, data, files))
        if url.endswith("/api/v2/media"):
            return FakeResponse({"id": "m1", "url": None}, 202)  # still processing
        return FakeResponse({"id": "113456789", "url": POST_URL})

    def get(url, headers=None, params=None, timeout=None):
        calls.append(("GET", url, headers, params, None))
        if "/api/v1/media/" in url:
            return FakeResponse({"id": "m1", "url": "https://files.example/m1.jpg"})
        return FakeResponse({"favourites_count": 6, "reblogs_count": 3, "replies_count": 1})

    monkeypatch.setattr(mastodon_client.requests, "post", post)
    monkeypatch.setattr(mastodon_client.requests, "get", get)
    monkeypatch.setattr(mastodon_client.time, "sleep", lambda s: None)
    return calls


def creative(**over):
    fields = dict(copy_text="Skip the morning queue.", image_prompt="a barista", image_bytes=b"jpeg", image_style="minimalist",
                  copy_tone="direct_factual", arm_index=0, headline="Your coffee, ready")
    return Creative(**{**fields, **over})


# --- switching it on ------------------------------------------------------------


def test_off_without_a_posting_token():
    assert "mastodon" not in active_channels()
    assert "distribution_mastodon" not in graph.route_after_gate_2({"rejected": False})


def test_on_with_a_posting_token(posting):
    assert active_channels()[-1] == "mastodon"
    assert graph.route_after_gate_2({"rejected": False}) == [
        "distribution_bluesky", "distribution_email", "distribution_mastodon"
    ]
    graph.build_graph()  # the node and its edges are wired


def test_the_search_token_alone_does_not_post(monkeypatch):
    # The existing token is read-only (search): it must not switch posting on.
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "read-only")
    assert not mastodon_client.posting_enabled()


# --- the client -----------------------------------------------------------------


def test_posts_the_ad_once_the_image_is_processed(posting, fake_http):
    url = mastodon_client.post_to_mastodon("Hello", image_bytes=b"jpeg", image_alt="Your coffee", idempotency_key="c1:1")
    assert url == POST_URL
    upload, poll, status = fake_http
    assert upload[1].endswith("/api/v2/media") and upload[3] == {"description": "Your coffee"}
    assert poll[0] == "GET" and poll[1].endswith("/api/v1/media/m1")  # waited for the 202 upload
    assert status[1].endswith("/api/v1/statuses")
    assert status[3] == {"status": "Hello", "visibility": "public", "media_ids[]": ["m1"]}
    assert status[2]["Idempotency-Key"] == "c1:1"
    assert status[2]["Authorization"] == "Bearer test-post-token"


def test_text_only_post_skips_the_upload(posting, fake_http):
    mastodon_client.post_to_mastodon("Hello")
    assert [c[1].rsplit("/api", 1)[1] for c in fake_http] == ["/v1/statuses"]


def test_metrics_use_bluesky_names(posting, fake_http):
    assert mastodon_client.get_mastodon_metrics(POST_URL) == {"likes": 6, "reposts": 3, "replies": 1}
    assert fake_http[0][1].endswith("/api/v1/statuses/113456789")


# --- delivery -------------------------------------------------------------------


def test_dry_run_posts_nothing(posting, monkeypatch):
    monkeypatch.setattr(distribution, "post_to_mastodon", lambda *a, **k: pytest.fail("posted in DRY_RUN"))
    assert distribution.post_mastodon("c1", 1, "Hello", b"jpeg").startswith("DRY_RUN: would post to Mastodon")


def test_live_post_and_retry_keep_the_image(posting, monkeypatch, delivery_ledger):
    monkeypatch.setenv("DRY_RUN", "false")
    sent = []

    def fake_post(text, image_bytes=None, image_alt="", idempotency_key=None):
        sent.append((text, image_bytes, image_alt, idempotency_key))
        if len(sent) <= 3:  # every in-process try fails: scheduled for a later retry
            raise ConnectionError("mastodon timeout")
        return POST_URL

    monkeypatch.setattr(distribution, "post_to_mastodon", fake_post)
    assert distribution.post_mastodon("c1", 1, "Hello", b"jpeg", image_alt="Alt").startswith("failed:")
    payload = json.loads(delivery_ledger.read_text())["c1:1:mastodon"]["payload"]
    assert base64.b64decode(payload["image_base64"]) == b"jpeg"

    assert distribution.resend_from_payload("mastodon", "c1", 1, payload, "u1") == POST_URL
    assert sent[-1] == ("Hello", b"jpeg", "Alt", "c1:1")
    assert ITERATION_COLUMN["mastodon"] == "mastodon_post_url"


# --- the graph node ---------------------------------------------------------------


@pytest.fixture
def node_env(monkeypatch):
    saved = {}
    monkeypatch.setattr(node, "brand_kit_for_campaign", lambda cid: None)
    monkeypatch.setattr(node, "upsert_iteration", lambda cid, uid, rnd, **f: saved.update(f))
    return saved


def test_node_posts_the_finished_ad(node_env, monkeypatch):
    calls = []
    monkeypatch.setattr(node, "post_mastodon", lambda *a, **k: calls.append((a, k)) or POST_URL)
    state = {"campaign_id": "c1", "user_id": "u1", "round_id": 2, "creative": creative(), "domain_category": "food_beverage"}
    assert node.distribution_mastodon_node(state) == {"mastodon_post_url": POST_URL}
    (args, kwargs), = calls
    assert args == ("c1", 2, "Skip the morning queue.")
    assert kwargs["image_bytes"] == b"jpeg" and kwargs["image_alt"] == "Your coffee, ready"
    assert node_env == {"mastodon_post_url": POST_URL}


def test_node_blocks_unsafe_copy(node_env, monkeypatch):
    monkeypatch.setattr(node, "post_mastodon", lambda *a, **k: pytest.fail("blocked copy was posted"))
    state = {"campaign_id": "c1", "user_id": "u1", "round_id": 1, "creative": creative(copy_text="Call 555-123-4567 now")}
    assert node.distribution_mastodon_node(state)["mastodon_post_url"].startswith("dead: blocked by brand-safety checks")


# --- guardrails -------------------------------------------------------------------


def test_mastodon_allows_500_characters():
    text = "word " * 80  # 400 characters: too long for Bluesky, fine for Mastodon
    assert guardrails.prepare_for_channel(text.strip(), "bluesky")[0] is None
    assert guardrails.prepare_for_channel(text.strip(), "mastodon")[1] is None
    assert guardrails.prepare_for_channel("x" * 501, "mastodon")[1].startswith("blocked")


def test_short_disclaimer_is_added_on_mastodon():
    text, _ = guardrails.prepare_for_channel("Budget smarter.", "mastodon", domain_category="finance_fintech")
    assert text == "Budget smarter. Not financial advice. Capital at risk."


# --- metrics and the bandit ---------------------------------------------------------


def test_metrics_reward_mastodon_engagement(monkeypatch):
    from src.capabilities import metrics
    from src.db import supabase_client

    stored = []
    monkeypatch.setattr(supabase_client, "get_iteration", lambda cid, rnd: {"mastodon_post_url": POST_URL})
    monkeypatch.setattr(supabase_client, "upsert_metric", lambda *a: stored.append(a))
    monkeypatch.setattr(metrics, "get_mastodon_metrics", lambda url: {"likes": 6, "reposts": 3, "replies": 1})
    result = metrics.collect_metrics("c1", "u1", 1)
    assert result.channel_rewards == {"mastodon": 10 / 50}
    assert stored[0][3] == "mastodon"


@pytest.mark.parametrize("ref", ["DRY_RUN: would post to Mastodon: 'Hi'", "failed: timeout", "dead: blocked"])
def test_unposted_rounds_are_not_measured(monkeypatch, ref):
    from src.capabilities import metrics
    from src.db import supabase_client

    monkeypatch.setattr(supabase_client, "get_iteration", lambda cid, rnd: {"mastodon_post_url": ref})
    monkeypatch.setattr(metrics, "get_mastodon_metrics", lambda url: pytest.fail("measured an unposted round"))
    assert metrics.collect_metrics("c1", "u1", 1).channel_rewards == {}


def test_bandit_reads_mastodon_as_a_social_feed():
    # Shares Bluesky's context slot, so the stored arm matrices keep their size.
    assert bandit.CONTEXT_DIM == 24
    a = bandit.build_context_vector("25-34", "mid", "mastodon", "food_beverage")
    b = bandit.build_context_vector("25-34", "mid", "bluesky", "food_beverage")
    assert np.array_equal(a, b)
