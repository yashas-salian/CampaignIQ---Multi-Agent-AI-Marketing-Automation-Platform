"""Bandit arm updates are compare-and-swap: concurrent feedback can't lose an update."""
import numpy as np
import pytest

from src.tools import bandit


class FakeArms:
    """bandit_arms with one row; `interfere` lets another 'worker' write between our read and write."""

    def __init__(self, interfere: int = 0):
        dim = bandit.CONTEXT_DIM
        self.row = {"arm_index": 3, "a_matrix": np.eye(dim).tolist(), "b_vector": [0.0] * dim, "pulls": 0, "total_reward": 0.0}
        self.interfere = interfere

    def table(self, name):
        return _Q(self)


class _Q:
    def __init__(self, db):
        self.db, self.filters, self.patch = db, {}, None

    def select(self, *a):
        return self

    def single(self):
        return self

    def update(self, patch):
        self.patch = patch
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def execute(self):
        db = self.db
        if self.patch is None:
            return type("R", (), {"data": dict(db.row)})()
        if db.interfere:  # someone else's update lands first
            db.interfere -= 1
            db.row = {**db.row, "pulls": db.row["pulls"] + 1, "total_reward": db.row["total_reward"] + 1.0}
        if all(db.row[k] == v for k, v in self.filters.items()):
            db.row = {**db.row, **self.patch}
            return type("R", (), {"data": [db.row]})()
        return type("R", (), {"data": []})()


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)


def _context():
    v = np.zeros(bandit.CONTEXT_DIM)
    v[0] = 1.0
    return v


def test_an_update_lands_once(monkeypatch, no_sleep):
    db = FakeArms()
    monkeypatch.setattr(bandit, "get_client", lambda: db)
    bandit.update_arm(3, _context(), 0.5)
    assert db.row["pulls"] == 1 and db.row["total_reward"] == 0.5 and db.row["b_vector"][0] == 0.5


def test_a_concurrent_update_is_kept_not_overwritten(monkeypatch, no_sleep):
    db = FakeArms(interfere=1)
    monkeypatch.setattr(bandit, "get_client", lambda: db)
    bandit.update_arm(3, _context(), 0.5)
    # Both updates count: the other worker's (+1.0) and ours (+0.5) after a re-read.
    assert db.row["pulls"] == 2 and db.row["total_reward"] == 1.5


def test_endless_contention_raises_instead_of_writing_stale_data(monkeypatch, no_sleep):
    db = FakeArms(interfere=99)
    monkeypatch.setattr(bandit, "get_client", lambda: db)
    with pytest.raises(bandit.ArmUpdateConflict):
        bandit.update_arm(3, _context(), 0.5)
