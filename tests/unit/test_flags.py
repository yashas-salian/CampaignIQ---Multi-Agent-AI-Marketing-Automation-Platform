import pytest

from src import flags


class FakeRpc:
    def __init__(self, value=None, error: Exception | None = None):
        self.value, self.error, self.calls = value, error, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("Result", (), {"data": self.value})()


@pytest.fixture(autouse=True)
def fresh():
    flags.clear_cache()
    yield
    flags.clear_cache()


def use_db(monkeypatch, fake):
    monkeypatch.setattr("src.db.supabase_client.get_client", lambda: fake)
    return fake


def test_env_override_wins_without_a_db_call(monkeypatch):
    fake = use_db(monkeypatch, FakeRpc(value=False))
    monkeypatch.setenv("FLAG_NEW_THING", "true")
    assert flags.is_enabled("new_thing", "u1") is True
    monkeypatch.setenv("FLAG_NEW_THING", "off")
    assert flags.is_enabled("new_thing", "u1") is False
    assert fake.calls == []


def test_database_decides_and_is_cached(monkeypatch):
    fake = use_db(monkeypatch, FakeRpc(value=True))
    assert flags.is_enabled("beta", "u1") is True
    assert flags.is_enabled("beta", "u1") is True
    assert fake.calls == [("feature_enabled_for", {"flag_key": "beta", "uid": "u1"})]


def test_a_failed_lookup_returns_the_default(monkeypatch):
    use_db(monkeypatch, FakeRpc(error=ConnectionError("db down")))
    assert flags.is_enabled("beta", "u1") is False
    assert flags.is_enabled("beta", "u1", default=True) is True
