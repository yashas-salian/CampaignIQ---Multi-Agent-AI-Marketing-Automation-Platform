import requests

from src.scheduler import uptime


class Resp:
    def __init__(self, status):
        self.status_code = status


def test_probe_classifies_status_and_errors(monkeypatch):
    monkeypatch.setattr(uptime.requests, "request", lambda *a, **k: Resp(401))
    assert uptime._probe("GET", "https://x", (200, 401))[0] is True
    assert uptime._probe("GET", "https://x", (200,))[2] == "HTTP 401"

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(uptime.requests, "request", boom)
    ok, _, detail = uptime._probe("GET", "https://x", (200,))
    assert ok is False and detail == "ConnectionError"


def test_all_components_are_checked(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://ref.supabase.co")
    seen = []
    monkeypatch.setattr(uptime, "_probe", lambda method, url, ok, headers=None: seen.append((method, url)) or (True, 5, None))
    assert set(uptime.checks()) == {"website", "database_api", "authentication", "edge_functions", "public_api"}
    assert ("OPTIONS", "https://ref.supabase.co/functions/v1/api") in seen
