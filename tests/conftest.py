"""Shared test setup.

Unit tests never touch the network, Supabase or Groq: the environment below is
fake, and `no_network` fails any test that opens a socket. Integration tests
(marked `integration`) opt out of that guard and use the local Supabase
Postgres instead.
"""
import base64
import os
import socket

import pytest

# Set before any src module is imported (some read env at import time). Real
# values from .env never override these: load_dotenv() doesn't overwrite.
os.environ.update(
    {
        "GROQ_API_KEY": "test-groq-key",
        "SUPABASE_URL": "http://supabase.invalid",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-role",
        "SETTINGS_ENCRYPTION_KEY": base64.b64encode(b"k" * 32).decode(),
        "FORCE_FREE_TIER": "true",
        "DRY_RUN": "true",
        "DOMAIN_CLASSIFIER": "llm",
        "ENABLE_REDDIT": "false",
        "MCP_USER_ID": "",
        "DOMAIN_MODEL_HF_REPO": "",
        "HF_TOKEN": "",
        "MASTODON_ACCESS_TOKEN": "",
        "MASTODON_POST_TOKEN": "",
        "TRACK_CLICK_BASE_URL": "",
        "PAID_LLM_API_KEY": "",
        "PAID_IMAGE_API_KEY": "",
        "PAID_JUDGE_API_KEY": "",
        # Image providers: tests opt in per case, never with real keys.
        "OPENAI_API_KEY": "",
        "OPENAI_IMAGE_GEN": "off",
        "CLOUDFLARE_ACCOUNT_ID": "",
        "CLOUDFLARE_API_TOKEN": "",
        "GEMINI_API_KEY": "",
    }
)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        return

    real_connect = socket.socket.connect

    def guarded(sock, address):
        # Loopback stays allowed: asyncio's event loop on Windows talks to
        # itself through a localhost socket pair.
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"unit tests must not open network connections (tried {host})")
        return real_connect(sock, address)

    real_getaddrinfo = socket.getaddrinfo

    def resolve(host, *args, **kwargs):
        # Fail DNS fast too: a real lookup of a fake host costs seconds per test.
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise RuntimeError(f"unit tests must not resolve external hosts (tried {host})")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture(autouse=True)
def delivery_ledger(tmp_path, monkeypatch):
    """Each test gets its own empty file-backed delivery ledger, and no real
    sleeping between in-process send retries."""
    monkeypatch.setenv("DELIVERY_LEDGER", "file")
    monkeypatch.setenv("DEDUP_STORE_PATH", str(tmp_path / "deliveries.json"))
    monkeypatch.setattr("src.capabilities.delivery.time.sleep", lambda s: None)
    return tmp_path / "deliveries.json"


class FakeLLM:
    """Stands in for an LLMProvider: returns queued replies, records prompts."""

    free_tier = False  # behaves like a paid/BYOK provider unless a test says otherwise

    def __init__(self, *replies: str):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


@pytest.fixture
def fake_llm():
    return FakeLLM
