"""Competitor intelligence (src/capabilities/competitors.py): safe, permitted
fetching; observed events from pages, feeds, news and posts; one story per
event however many outlets ran it; the deterministic recommendation with
all four options; inferred intent kept apart; the forecast and its check.
Database rules (who manages the watch list, RLS) are in
tests/integration/test_db_competitors.py."""
from datetime import datetime, timedelta, timezone

import pytest

from src.capabilities import competitors as ci
from src.capabilities.competitors import (
    ACTIONS, Observed, assign_stories, classify_item, diff_page, extract_page, make_prediction, mentions, news_events,
    parse_feed, recommend, resolve_prediction, source_status, theme_events,
)
from src.eval.competitor_benchmark import run as benchmark

NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)


class TestSafeFetching:
    def test_only_public_addresses(self, monkeypatch):
        def resolve(addresses):
            return lambda host, port: [(None, None, None, None, (a, 0)) for a in addresses]

        monkeypatch.setattr(ci.socket, "getaddrinfo", resolve(["93.184.216.34"]))
        assert ci.public_host("example.com")
        for private in (["127.0.0.1"], ["10.0.0.5"], ["169.254.169.254"], ["192.168.1.2"], ["93.184.216.34", "10.0.0.1"], ["::1"]):
            monkeypatch.setattr(ci.socket, "getaddrinfo", resolve(private))
            assert not ci.public_host("sneaky.example"), private

    def test_a_redirect_into_a_private_network_is_refused(self, monkeypatch):
        class R:
            is_redirect, status_code = True, 302
            headers = {"location": "http://internal.example/admin"}

        monkeypatch.setattr(ci, "public_host", lambda host: host == "brewco.example")
        monkeypatch.setattr("requests.get", lambda *a, **k: R())
        with pytest.raises(ci.FetchError, match="not a public web address"):
            ci._get("https://brewco.example/pricing")

    @pytest.mark.parametrize("status, body, allowed", [
        (404, b"", True),                                     # no robots.txt: allowed (RFC 9309)
        (503, b"", False),                                    # unreachable: assume disallowed
        (200, b"User-agent: *\nDisallow: /pricing", False),
        (200, b"User-agent: CampaignIQ-CompetitorWatch\nDisallow: /\n\nUser-agent: *\nAllow: /", False),
        (200, b"User-agent: *\nDisallow: /admin", True),
    ])
    def test_robots_txt_is_respected(self, status, body, allowed):
        ci._robots_cache.clear()
        assert ci.robots_allows("https://brewco.example/pricing", fetch=lambda url, accept=None: (status, body, "text/plain")) is allowed


PAGE = """<html><head><title>BrewCo | Coffee ready on arrival</title>
<meta name="description" content="Order ahead and skip the queue.">
<script>var price = "$99.99"; // not on the page</script></head>
<body><h1>Coffee ready when you arrive</h1><h2>Plans</h2>
<p>Basic $4.99/mo. Plus $9.99/mo.</p><p>Get 20% off your first month. Terms apply.</p></body></html>"""


class TestPages:
    def test_extract_keeps_the_positioning_not_the_page(self):
        e = extract_page(PAGE)
        assert e["headline"] == "Coffee ready when you arrive" and e["description"] == "Order ahead and skip the queue."
        assert e["prices"] == ["$4.99/mo", "$9.99/mo"]  # the script's $99.99 isn't on the page
        assert e["offers"] == ["Get 20% off your first month."]

    def test_the_first_snapshot_is_only_a_baseline(self):
        assert diff_page(None, extract_page(PAGE), url="https://brewco.example", outlet="brewco.example") == []

    def test_changes_become_observed_events_with_before_and_after(self):
        before = extract_page(PAGE)
        after = extract_page(PAGE.replace("20% off your first month", "40% off your first three months")
                             .replace("Coffee ready when you arrive", "Your morning, handled")
                             .replace("$9.99/mo", "$7.99/mo").replace("<h2>Plans</h2>", "<h2>Plans</h2><h2>Introducing BrewCo Cold</h2>"))
        events = {(e.kind, e.observed.get("change") or e.observed.get("field") or "launch"): e
                  for e in diff_page(before, after, url="https://brewco.example", outlet="brewco.example")}
        assert ("OFFER_CHANGE", "added") in events and ("OFFER_CHANGE", "removed") in events
        assert events[("OFFER_CHANGE", "prices")].observed == {"change": "prices", "before": ["$4.99/mo", "$9.99/mo"],
                                                               "after": ["$4.99/mo", "$7.99/mo"]}
        shift = events[("MESSAGING_SHIFT", "headline")]
        assert shift.observed["before"] == "Coffee ready when you arrive" and shift.observed["after"] == "Your morning, handled"
        assert ("PRODUCT_LAUNCH", "launch") in events
        assert all(e.confidence == 0.9 and e.url == "https://brewco.example" for e in events.values())

    def test_the_same_change_seen_twice_is_one_story(self):
        before, after = extract_page(PAGE), extract_page(PAGE.replace("20% off", "30% off"))
        a = diff_page(before, after, url="https://b.example", outlet="b")
        b = diff_page(before, after, url="https://b.example", outlet="b")
        assert [e.story_key for e in a] == [e.story_key for e in b]


class TestNewsAndPosts:
    def test_what_a_headline_reports(self):
        assert classify_item("BrewCo launches a cold brew subscription") == "PRODUCT_LAUNCH"
        assert classify_item("BrewCo slashes prices by 30%") == "OFFER_CHANGE"
        assert classify_item("BrewCo rebrands with a new ad campaign") == "MESSAGING_SHIFT"
        assert classify_item("BrewCo CEO talks about the coffee market") is None

    def test_names_match_whole_words(self):
        assert mentions("StrideRun debuts a trainer", ["StrideRun"])
        assert not mentions("Stride and run: favourite trails", ["StrideRun"])
        assert not mentions("BrewCompany opens a store", ["BrewCo"])

    def test_syndicated_copies_and_rewrites_are_one_story(self):
        articles = [
            {"title": "BrewCo launches cold brew subscription for commuters", "url": "u1", "outlet": "Reuters", "published_at": None},
            {"title": "BrewCo launches cold brew subscription for commuters - Reuters", "url": "u2", "outlet": "Yahoo", "published_at": None},
            {"title": "BrewCo's new cold brew subscription targets commuters", "url": "u3", "outlet": "Verge", "published_at": None},
            {"title": "BrewCo slashes iced drink prices 30% for summer", "url": "u4", "outlet": "CNBC", "published_at": None},
            {"title": "Best coffee shops in Austin, including BrewCo", "url": "u5", "outlet": "Eater", "published_at": None},
        ]
        events = assign_stories(news_events(articles, ["BrewCo"]), [])
        assert len(events) == 4 and len({e.story_key for e in events}) == 2  # 4 reports, 2 independent stories
        # A later report joins the story already stored.
        known = [{"story_key": events[0].story_key, "kind": "PRODUCT_LAUNCH", "title": events[0].title}]
        later = assign_stories(news_events([{"title": "BrewCo launches commuter cold brew subscription", "url": "u6",
                                             "outlet": "AP", "published_at": None}], ["BrewCo"]), known)
        assert later[0].story_key == events[0].story_key

    def test_feeds_rss_and_atom(self):
        rss = """<rss><channel><item><title>Introducing BrewCo Cold</title><link>https://b.example/cold</link>
        <pubDate>Sat, 24 Oct 2026 09:00:00 GMT</pubDate><description>&lt;p&gt;Our new cold brew.&lt;/p&gt;</description></item></channel></rss>"""
        atom = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Summer sale: 30% off</title>
        <link href="https://b.example/sale"/><updated>2026-10-20T10:00:00Z</updated><summary>Iced drinks</summary></entry></feed>"""
        assert parse_feed(rss) == [{"title": "Introducing BrewCo Cold", "url": "https://b.example/cold",
                                    "published_at": "2026-10-24T09:00:00+00:00", "text": "Our new cold brew."}]
        assert parse_feed(atom)[0]["url"] == "https://b.example/sale"
        assert parse_feed("not xml") == []

    def test_a_new_content_theme_needs_several_recent_posts(self):
        def post(day, text):
            return {"title": text, "text": "", "url": f"https://bsky.app/{day}", "published_at": (NOW - timedelta(days=day)).isoformat()}

        earlier = [post(20 + i, f"Our coffee menu update {i}") for i in range(6)]
        recent = [post(i, t) for i, t in enumerate(["Oat milk is here", "Try oat milk in your latte", "Oat milk cold brew", "Hello Monday"])]
        themes = theme_events(earlier + recent, names=["BrewCo"], outlet="@brewco", now=NOW)
        assert themes and themes[0].kind == "CONTENT_THEME" and "oat" in themes[0].observed["term"]
        assert themes[0].observed["examples"] and themes[0].observed["recent"] >= 3
        assert theme_events(earlier + recent[:2], names=["BrewCo"], outlet="@brewco", now=NOW) == []


def event(kind, **kw):
    return {"id": "e1", "kind": kind, "summary": kw.pop("summary", "x"), "observed": kw.pop("observed", {}),
            "confidence": kw.pop("confidence", 0.9), "source_kind": kw.pop("source_kind", "webpage"), "reports": 1, **kw}


RELEVANT = {"relevant": True, "live_campaigns": [{"id": "c1", "idea": "cold brew"}]}


class TestRecommendation:
    @pytest.mark.parametrize("ev, rel, hist, pick", [
        (event("OFFER_CHANGE", observed={"change": "added", "after": "40% off your first month"}), RELEVANT, {}, "RESPOND"),
        (event("OFFER_CHANGE", observed={"change": "added", "after": "10% off"}), RELEVANT, {}, "DIFFERENTIATE"),
        (event("OFFER_CHANGE", observed={"change": "added", "after": "40% off"}), RELEVANT, {"deeper_than_before": False}, "DIFFERENTIATE"),
        (event("OFFER_CHANGE", observed={"change": "removed", "before": "40% off"}), RELEVANT, {}, "NO_ACTION"),
        (event("PRODUCT_LAUNCH"), RELEVANT, {}, "RESPOND"),
        (event("MESSAGING_SHIFT"), RELEVANT, {}, "DIFFERENTIATE"),
        (event("PRODUCT_LAUNCH", source_kind="news", confidence=0.6), RELEVANT, {}, "MONITOR"),  # one unconfirmed report
        (event("PRODUCT_LAUNCH"), {"relevant": False, "live_campaigns": []}, {}, "MONITOR"),
        (event("CONTENT_THEME"), {"relevant": False, "live_campaigns": []}, {}, "NO_ACTION"),
    ])
    def test_the_policy(self, ev, rel, hist, pick):
        got, options, confidence = recommend(ev, rel, hist)
        assert got == pick
        assert [o["action"] for o in options] == list(ACTIONS)  # all four, NO_ACTION always among them
        assert sum(o["recommended"] for o in options) == 1 and all(o["reasons"] for o in options)
        assert 0 < confidence <= 0.95

    def test_relevance_is_about_live_campaigns_in_that_market(self):
        comp = {"name": "BrewCo", "category_keyword": "cold brew coffee"}
        assert ci.relevance(comp, [{"id": "c1", "idea": "Order-ahead cold brew coffee for commuters"}])["relevant"]
        assert not ci.relevance(comp, [{"id": "c2", "idea": "Yoga classes for seniors"}])["relevant"]

    def test_history_says_whether_an_offer_is_deeper_than_before(self):
        past = [event("OFFER_CHANGE", observed={"after": "20% off"}, observed_at=(NOW - timedelta(days=30)).isoformat()) | {"id": "old"}]
        assert ci.history_context(event("OFFER_CHANGE", observed={"after": "35% off"}), past)["deeper_than_before"] is True


class TestExplanations:
    def test_inferred_intent_is_labelled_and_falls_back(self, monkeypatch):
        monkeypatch.setattr("src.providers.registry.get_llm", lambda user_id=None: (_ for _ in ()).throw(RuntimeError("no provider")))
        out = ci.explain(event("OFFER_CHANGE"), {"name": "BrewCo"})
        assert out and all(h["inferred"] and h["source"] == "template" for h in out)

    def test_llm_hypotheses_are_kept_only_when_there_are_alternatives(self, monkeypatch):
        answers = iter([{"hypotheses": [{"hypothesis": "Clearing summer stock", "would_confirm": "The sale ends in August",
                                         "would_refute": "It runs all year"},
                                        {"hypothesis": "Answering a rival's discount", "would_confirm": "A rival cut first",
                                         "would_refute": "No rival moved"}]},
                        {"hypotheses": [{"hypothesis": "Only one story"}]}])
        monkeypatch.setattr("src.providers.registry.get_llm", lambda user_id=None: object())
        monkeypatch.setattr("src.llm_json.generate_json", lambda llm, prompt, system=None: next(answers))
        two = ci.explain(event("OFFER_CHANGE"), {"name": "BrewCo"})
        assert [h["hypothesis"] for h in two] == ["Clearing summer stock", "Answering a rival's discount"] and all(h["inferred"] for h in two)
        assert ci.explain(event("OFFER_CHANGE"), {"name": "BrewCo"})[0]["source"] == "template"  # one story isn't enough


class TestForecast:
    def series(self, n=120, bump=False):
        weeks = [(datetime(2024, 1, 7) + timedelta(weeks=i)).strftime("%Y-%m-%d") for i in range(n)]
        values = [50 + 10 * ((i % 52) / 52) + (3 if i % 2 else 0) for i in range(n)]
        if bump:
            values[-2:] = [80, 80]
        return weeks, values

    def test_a_prediction_with_an_interval_and_a_date_to_check_it(self):
        weeks, values = self.series()
        p = make_prediction("cold brew coffee", now=NOW, series=(weeks, values))
        assert p["origin_week"] == weeks[-1] and p["horizon_days"] == 14 and p["model_version"] == "trend-v1"
        assert p["interval_low"] <= p["predicted_change"] <= p["interval_high"]
        assert datetime.fromisoformat(p["resolve_after"]) > datetime.fromisoformat(weeks[-1] + "T00:00:00+00:00") + timedelta(days=14)

    def test_not_enough_history_means_no_forecast(self):
        weeks, values = self.series(40)
        assert make_prediction("x", now=NOW, series=(weeks, values)) is None

    def test_checking_it_later(self):
        weeks, values = self.series(122, bump=True)
        pred = {"keyword": "x", "origin_week": weeks[-3], "predicted_change": 0.12, "interval_low": -0.05, "interval_high": 0.2}
        out = resolve_prediction(pred, series=(weeks, values))
        assert out["status"] == "resolved" and out["observed_change"] > 0.3 and out["inside_interval"] is False
        assert out["materialized"] is True and out["abs_error"] == pytest.approx(out["observed_change"] - 0.12, abs=1e-4)
        assert resolve_prediction({**pred, "origin_week": weeks[-1]}, series=(weeks, values))["status"] == "pending"
        assert resolve_prediction({**pred, "origin_week": "1999-01-03"}, series=(weeks, values))["status"] == "unresolvable"


def test_a_source_that_keeps_failing_is_stale_not_current():
    ok = {"last_ok_at": (NOW - timedelta(hours=10)).isoformat()}
    old = {"last_ok_at": (NOW - timedelta(days=5)).isoformat()}
    assert source_status(ok, ci.SourceResult("unavailable", error="503"), NOW)["status"] == "unavailable"
    assert source_status(old, ci.SourceResult("unavailable", error="503"), NOW)["status"] == "stale"
    assert source_status(old, ci.SourceResult("ok"), NOW) | {} == {"last_fetched_at": NOW.isoformat(), "last_error": None,
                                                                    "status": "ok", "last_ok_at": NOW.isoformat()}
    assert source_status(ok, ci.SourceResult("blocked_by_robots", error="robots"), NOW)["status"] == "blocked_by_robots"


def test_a_failing_source_never_raises(monkeypatch):
    monkeypatch.setattr(ci, "robots_allows", lambda url: True)
    monkeypatch.setattr(ci, "_get", lambda *a, **k: (_ for _ in ()).throw(TimeoutError("slow")))
    result = ci.fetch_source({"id": "s1", "kind": "webpage", "locator": "https://b.example"}, {"name": "BrewCo"}, now=NOW)
    assert result.status == "unavailable" and "TimeoutError" in result.error


def test_competitor_moves_are_review_flags_for_the_decision_not_score():
    from src.capabilities.decision import DecisionInputs, evaluate

    base = DecisionInputs(idea="Order-ahead cold brew for commuters", trend={"mean_interest": 50, "latest_interest": 55,
                          "fetched_at": NOW.isoformat()}, news={"total_results": 40, "fetched_at": NOW.isoformat()})
    moved = DecisionInputs(**{**base.__dict__, "competitor_activity": [{"competitor": "BrewCo", "kind": "OFFER_CHANGE",
                                                                         "summary": "New offer: 40% off", "url": "https://b.example"}]})
    a, b = evaluate(base, now=NOW), evaluate(moved, now=NOW)
    assert (a.decision, a.opportunity_score) == (b.decision, b.opportunity_score)
    flag = next(f for f in b.review_flags if f["code"] == "COMPETITOR_MOVE")
    assert flag["detail"] == "BrewCo: New offer: 40% off" and flag["url"] == "https://b.example"


def test_the_benchmark_meets_its_bar():
    r = benchmark()
    test = r["forecast"]["test"]
    assert test["model_mae"] < test["naive_mae"]          # beats "no change" on years it never saw
    assert test["coverage"] >= 0.7                         # the 80% interval holds reasonably out of sample
    s = r["signals"]
    assert s["stories_found"] == s["true_stories"] < s["move_articles"]  # duplicates don't inflate the count
    assert s["false_events"] == 0 and s["kind_accuracy"] >= 0.9
