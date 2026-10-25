import pytest

from src.capabilities import metrics as metrics_mod
from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.capabilities.experiments import split_recipients, two_proportion_test
from src.graph.nodes import distribution_email, variant_b
from src.tools import bandit

PERSONA = Persona(name="Ava", demographics="d", psychographics="p", channel_fit="email", messaging_angle="m",
                  age_bracket="25-34", income_tier="mid")


def creative(copy: str, arm: int = 0) -> Creative:
    return Creative(copy_text=copy, image_prompt="i", image_bytes=b"", image_style="minimalist", copy_tone="humorous", arm_index=arm)


class TestStatistics:
    def test_split_is_deterministic_and_balanced(self):
        a, b = split_recipients(["d@x.io", "A@x.io", "c@x.io", "b@x.io", "a@x.io", " "], salt="c1")
        assert sorted(a + b) == ["a@x.io", "b@x.io", "c@x.io", "d@x.io"] and len(a) == len(b) == 2  # de-duplicated, case-folded
        assert split_recipients(["b@x.io", "d@x.io", "a@x.io", "c@x.io"], salt="c1") == (a, b)  # order of input doesn't matter

    def test_split_is_not_alphabetical_and_differs_between_campaigns(self):
        people = [f"user{i:03d}@x.io" for i in range(200)]
        a, _ = split_recipients(people, salt="c1")
        assert a != people[0::2]  # not the old alternate-by-name split
        first_half = sum(1 for p in a if p < "user100")
        assert 35 <= first_half <= 65  # names early and late in the alphabet land in both halves
        assert split_recipients(people, salt="c2")[0] != a

    def test_bayesian_lift_is_stable_with_a_zero_baseline(self):
        from src.capabilities.experiments import bayesian_ab

        zero = bayesian_ab(0, 20, 3, 20)
        assert zero["expected_lift"] is None and 0 < zero["expected_difference"] < 0.3
        some = bayesian_ab(1, 20, 4, 20)
        assert some["expected_lift"] is not None and some["expected_lift"] < 20

    def test_clear_difference_is_significant(self):
        result = two_proportion_test(20, 1000, 60, 1000)
        assert result["significant"] and result["winner"] == "b" and result["p_value"] < 0.001
        assert result["lift"] == pytest.approx(2.0)

    def test_small_samples_are_not_called(self):
        result = two_proportion_test(1, 10, 3, 10)
        assert not result["significant"] and result["winner"] is None

    def test_degenerate_inputs(self):
        assert two_proportion_test(0, 0, 0, 0)["p_value"] is None
        assert two_proportion_test(0, 50, 0, 50)["p_value"] == 1.0


def test_bandit_ranks_arms():
    import numpy as np

    arms = [{"arm_index": i, "a_matrix": np.eye(bandit.CONTEXT_DIM).tolist(),
             "b_vector": (np.ones(bandit.CONTEXT_DIM) * (0.1 * (i % 5))).tolist()} for i in range(20)]
    bandit_get = bandit._get_all_arms
    try:
        bandit._get_all_arms = lambda: arms
        top = bandit.select_arms_for_campaign("25-34", "mid", "education", ["email"], k=2)
    finally:
        bandit._get_all_arms = bandit_get
    assert [t[0] for t in top] == [4, 9] and top[0][1:] == bandit.ARMS[4]


class TestVariantNode:
    STATE = {"idea": "Meal kits", "primary_persona": PERSONA, "domain_category": "food_beverage", "campaign_id": "c1",
             "user_id": "u1", "round_id": 1, "email_to": ["a@x.io", "b@x.io"], "ab_test": True}

    def test_skipped_without_ab_test_or_with_one_recipient(self, monkeypatch):
        monkeypatch.setattr(variant_b, "generate_creative", lambda *a, **k: pytest.fail("no variant expected"))
        assert variant_b.generate_variant_b_node({**self.STATE, "ab_test": False}) == {"creative_b": None}
        assert variant_b.generate_variant_b_node({**self.STATE, "email_to": ["a@x.io"]}) == {"creative_b": None}

    def test_uses_the_second_best_arm(self, monkeypatch):
        seen, saved = {}, {}
        monkeypatch.setattr(variant_b, "select_arms_for_campaign", lambda *a, **k: [(4, "minimalist", "humorous"), (9, "humor_meme", "humorous")])
        monkeypatch.setattr(variant_b, "brand_kit_for_campaign", lambda cid: None)
        monkeypatch.setattr(variant_b, "generate_creative", lambda *a, **k: seen.update(k) or creative("B copy", 9))
        monkeypatch.setattr(variant_b, "upsert_iteration", lambda *a, **k: saved.update(k))
        out = variant_b.generate_variant_b_node(self.STATE)
        assert seen["arm"] == (9, "humor_meme", "humorous") and out["creative_b"].copy_text == "B copy"
        assert saved["copy_text_b"] == "B copy" and saved["arm_index_b"] == 9


def test_email_node_sends_each_half_its_variant(monkeypatch):
    sends, saved = [], {}
    monkeypatch.setattr(distribution_email, "brand_kit_for_campaign", lambda cid: None)
    monkeypatch.setattr(distribution_email, "send_campaign_email",
                        lambda cid, rid, to, **k: sends.append((tuple(to), k.get("channel", "email"), k["html"])) or f"id-{len(sends)}")
    monkeypatch.setattr(distribution_email, "upsert_iteration", lambda *a, **k: saved.update(k))
    state = {"campaign_id": "c1", "user_id": "u1", "round_id": 1, "domain_category": "other", "idea": "Meal kits",
             "email_to": ["d@x.io", "c@x.io", "b@x.io", "a@x.io"], "creative": creative("Copy A"), "creative_b": creative("Copy B")}
    distribution_email.distribution_email_node(state)
    half_a, half_b = split_recipients(state["email_to"], salt="c1")  # the same split metrics use
    assert [(s[0], s[1]) for s in sends] == [(tuple(half_a), "email"), (tuple(half_b), "email_b")]
    assert "Copy A" in sends[0][2] and "Copy B" in sends[1][2]
    assert saved == {"email_id": "id-1", "email_id_b": "id-2"}


def test_metrics_compare_the_variants(monkeypatch):
    clicks = {"email": 5, "email_b": 40}
    rows = []
    monkeypatch.setattr("src.db.supabase_client.get_iteration", lambda cid, r: {"email_id": "em_a", "email_id_b": "em_b"})
    monkeypatch.setattr("src.db.supabase_client.get_click_count", lambda cid, r, channel="email": clicks[channel])
    monkeypatch.setattr("src.db.supabase_client.upsert_metric", lambda *a: rows.append(a))
    recipients = [f"user{i}@x.io" for i in range(200)]
    result = metrics_mod.collect_metrics("c1", "u1", 1, email_to=recipients)
    assert result.channel_rewards == {"email": 0.05, "email_b": 0.4}
    test = result.raw["email_b"]["ab_test"]
    assert test["winner"] == "b" and test["significant"]
    assert [r[3] for r in rows] == ["email", "email_b"]


def test_one_channel_failing_keeps_the_others(monkeypatch):
    """A Bluesky outage must not lose Mastodon's or email's numbers, and the
    failed channel is "not measured", never a zero."""
    rows = []
    monkeypatch.setattr("src.db.supabase_client.get_iteration", lambda cid, r: {
        "bluesky_post_uri": "at://x/app.bsky.feed.post/1", "mastodon_post_url": "https://m.social/@a/1", "email_id": "em_1"})
    monkeypatch.setattr("src.db.supabase_client.get_click_count", lambda cid, r, channel="email": 2)
    monkeypatch.setattr("src.db.supabase_client.upsert_metric", lambda *a: rows.append(a[3]))

    def down(ref):
        raise ConnectionError("bluesky 502")

    monkeypatch.setattr(metrics_mod, "get_bluesky_metrics", down)
    monkeypatch.setattr(metrics_mod, "get_mastodon_metrics", lambda ref: {"likes": 5, "reposts": 0, "replies": 0})
    result = metrics_mod.collect_metrics("c1", "u1", 1, email_to=["a@x.io", "b@x.io"])
    assert set(result.channel_rewards) == {"mastodon", "email"} and "bluesky" not in result.raw
    assert rows == ["mastodon", "email"]


def test_a_failed_metrics_write_still_counts_the_reward(monkeypatch):
    monkeypatch.setattr("src.db.supabase_client.get_iteration", lambda cid, r: {"mastodon_post_url": "https://m.social/@a/1"})
    monkeypatch.setattr(metrics_mod, "get_mastodon_metrics", lambda ref: {"likes": 10, "reposts": 0, "replies": 0})

    def db_down(*a):
        raise ConnectionError("db")

    monkeypatch.setattr("src.db.supabase_client.upsert_metric", db_down)
    assert metrics_mod.collect_metrics("c1", "u1", 1).channel_rewards == {"mastodon": 0.2}
