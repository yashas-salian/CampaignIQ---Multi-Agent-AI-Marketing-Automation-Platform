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


class FakeDb(FakeRpc):
    """The RPC plus a feature_flags table holding `rows`."""

    def __init__(self, value, rows):
        super().__init__(value=value)
        self.rows = rows

    def table(self, name):
        assert name == "feature_flags"
        return _Query(self.rows)


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a):
        return self

    def eq(self, column, value):
        self.rows = [r for r in self.rows if r[column] == value]
        return self

    def limit(self, n):
        return self

    def execute(self):
        return type("Result", (), {"data": self.rows})()


def test_a_flag_with_no_row_keeps_its_default(monkeypatch):
    """llm_fallback defaults to on: an empty flags table must not switch the fallbacks off."""
    use_db(monkeypatch, FakeDb(value=False, rows=[]))
    assert flags.is_enabled("llm_fallback", "u1", default=True) is True
    flags.clear_cache()
    assert flags.is_enabled("llm_fallback", "u1") is False


def test_a_flag_switched_off_in_the_table_stays_off(monkeypatch):
    use_db(monkeypatch, FakeDb(value=False, rows=[{"key": "llm_fallback"}]))
    assert flags.is_enabled("llm_fallback", "u1", default=True) is False
