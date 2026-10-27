"""Market-moment alerts: spot when a live campaign's topic suddenly gets hot.

Feasibility saves each campaign's search keyword and the signals it saw at
launch (campaigns.market_watch). This sweep re-checks live campaigns about once
a day: when Google Trends interest or news coverage jumps well above that
baseline, it records an alert (market_alerts, shown in the app), tells the
organisation (Slack / email, like gate notices) and fires a market.moment
webhook. Read-only signals, so it never touches a campaign's run; any error is
logged and the campaign is tried again next time.

    python -m src.scheduler.market_watch
"""
import logging
from datetime import datetime, timedelta, timezone

from src.db.supabase_client import get_client
from src.languages import newsapi_language, trends_hl

log = logging.getLogger("market_watch")

WATCH_DAYS = 30  # only campaigns launched in the last month
RECHECK_HOURS = 20  # about once a day per campaign (the sweep runs hourly)
MAX_PER_SWEEP = 15  # Google Trends rate-limits hard: spread the checks out
COOLDOWN_DAYS = 3  # one alert of a kind per campaign per few days
TREND_RATIO, TREND_MIN = 1.5, 30  # interest index (0-100)
NEWS_RATIO, NEWS_MIN = 2.0, 10  # matching articles
DONE = ("completed", "rejected", "blocked", "failed")


def detect(baseline: dict, trend: dict | None, news: dict | None) -> list[dict]:
    """Pure spike rules: a list of {kind, detail} for whatever jumped."""
    found = []
    if trend and trend.get("latest_interest") is not None:
        latest = float(trend["latest_interest"])
        usual = float(baseline.get("trend_mean") or 0)
        if latest >= TREND_MIN and latest >= usual * TREND_RATIO:
            found.append({"kind": "trend", "detail": {
                "value": round(latest), "baseline": round(usual), "ratio": round(latest / usual, 1) if usual else None,
            }})
    if news and news.get("total_results") is not None:
        total = int(news["total_results"])
        usual_news = int(baseline.get("news_total") or 0)
        if total >= NEWS_MIN and total >= max(usual_news, 1) * NEWS_RATIO:
            found.append({"kind": "news", "detail": {
                "value": total, "baseline": usual_news, "ratio": round(total / usual_news, 1) if usual_news else None,
                "headline": (news.get("headlines") or [None])[0],
            }})
    return found


def _fetch(keyword: str, language: str) -> tuple[dict | None, dict | None]:
    trend = news = None
    try:
        from src.tools.trends import get_trend_interest

        trend = get_trend_interest(keyword, hl=trends_hl(language))
    except Exception as exc:
        log.warning("trends for %r failed: %s", keyword, exc)
    try:
        from src.tools.news import get_news_volume

        news = get_news_volume(keyword, language=newsapi_language(language))
    except Exception as exc:
        log.warning("news for %r failed: %s", keyword, exc)
    return trend, news


def scan(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    client = get_client()
    rows = (
        client.table("campaigns").select("id,org_id,idea,status,market_watch,created_at")
        .gte("created_at", (now - timedelta(days=WATCH_DAYS)).isoformat())
        .not_.is_("market_watch", "null").execute().data or []
    )
    due = [
        r for r in rows
        if r["status"] not in DONE and r["market_watch"].get("keyword")
        and (not r["market_watch"].get("checked_at")
             or datetime.fromisoformat(r["market_watch"]["checked_at"]) < now - timedelta(hours=RECHECK_HOURS))
    ]
    due.sort(key=lambda r: r["market_watch"].get("checked_at") or "")  # never-checked first
    raised = 0
    for campaign in due[:MAX_PER_SWEEP]:
        watch = campaign["market_watch"]
        try:
            trend, news = _fetch(watch["keyword"], watch.get("language", "en"))
            for alert in detect(watch.get("baseline") or {}, trend, news):
                if _recent(client, campaign["id"], alert["kind"], now):
                    continue
                detail = {"keyword": watch["keyword"], **alert["detail"]}
                client.table("market_alerts").insert({
                    "campaign_id": campaign["id"], "org_id": campaign["org_id"], "kind": alert["kind"], "detail": detail,
                }).execute()
                _announce(campaign, alert["kind"], detail)
                raised += 1
            _reevaluate(campaign, trend, news, now)
            _brand_risk(campaign, watch["keyword"], news, now)
            client.table("campaigns").update({"market_watch": {
                **watch, "checked_at": now.isoformat(),
                "last": {"trend_latest": (trend or {}).get("latest_interest"), "news_total": (news or {}).get("total_results")},
            }}).eq("id", campaign["id"]).execute()
        except Exception as exc:  # one campaign's failure never stops the sweep
            log.warning("market watch for %s failed: %s", campaign["id"], exc)
    return raised


def _brand_risk(campaign: dict, keyword: str, news: dict | None, now: datetime) -> None:
    """Crisis headlines about the campaign's topic pause it (circuit breaker). Never raises."""
    try:
        from src.capabilities.circuit_breaker import check_news

        check_news(campaign, keyword, {**(news or {}), "fetched_at": now.isoformat()} if news else None)
    except Exception as exc:
        log.warning("brand-risk check for %s failed: %s", campaign["id"], exc)


def _reevaluate(campaign: dict, trend: dict | None, news: dict | None, now: datetime) -> None:
    """A WAIT decision's trigger: with fresh signals in hand, decide again (never raises)."""
    try:
        from src.capabilities.decision import reevaluate_waiting
        from src.notifications import notify_decision_reevaluated

        decision = reevaluate_waiting(campaign, trend, news, now=now)
        if decision is not None:
            notify_decision_reevaluated(campaign["id"], "WAIT", decision.decision, decision.opportunity_score)
    except Exception as exc:
        log.warning("re-evaluating %s failed: %s", campaign["id"], exc)


def _recent(client, campaign_id: str, kind: str, now: datetime) -> bool:
    since = (now - timedelta(days=COOLDOWN_DAYS)).isoformat()
    return bool(
        client.table("market_alerts").select("id").eq("campaign_id", campaign_id).eq("kind", kind)
        .gte("created_at", since).limit(1).execute().data
    )


def _announce(campaign: dict, kind: str, detail: dict) -> None:
    from src.notifications import notify_market_moment

    notify_market_moment(campaign["id"], kind, detail)
    if campaign.get("org_id"):
        try:
            get_client().rpc("audit", {
                "p_org": campaign["org_id"], "p_action": "market.moment", "p_target_type": "campaign",
                "p_target_id": campaign["id"], "p_details": {"kind": kind, **detail},
            }).execute()
        except Exception as exc:
            log.warning("market.moment not audited: %s", exc)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    print(f"Market watch: {scan()} new alert(s).")
