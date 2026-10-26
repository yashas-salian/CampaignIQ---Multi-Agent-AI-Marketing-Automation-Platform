"""Notifications: the people who must act hear about it.

Who: notification_recipients() in the database.
  * 'approvers' (a gate is waiting, a market moment, a re-evaluation): the
    organisation's designated approvers (Settings → Team), or everyone who can
    approve when none are designated.
  * 'managers' (an approval is overdue, a campaign is held, email is paused):
    owners and admins.
Where, for each of them:
  * in the app: a notification in their inbox (the bell in the top bar);
  * by email, unless they turned it off: from the organisation's own Resend
    account when it's connected live (Settings → Email sending), else from the
    app's account when NOTIFY_EMAIL=true (Resend's free tier only delivers to
    its own address until a domain is verified);
  * Slack: org_settings.slack_webhook_url, one message for the channel.
Links point at APP_BASE_URL (the deployed frontend). Approving happens in the
app, signed in, so the quorum and role rules always apply.
A notification can never fail a campaign run: every error is logged and dropped.
"""
import html
import logging
import os

import requests

logger = logging.getLogger("notifications")

PREFIX = "[CampaignIQ]"


def _app_url(path: str) -> str:
    base = os.environ.get("APP_BASE_URL", "https://campaign-iq-multi-agent-ai-marketin.vercel.app").rstrip("/")
    return f"{base}{path}"


def _client():
    from src.db.supabase_client import get_client

    return get_client()


def _campaign(campaign_id: str) -> dict:
    return _client().table("campaigns").select("id,idea,org_id,user_id").eq("id", campaign_id).single().execute().data


def _settings(org_id: str) -> dict:
    found = _client().table("org_settings").select("*").eq("org_id", org_id).maybe_single().execute()
    return found.data if found and found.data else {}


def _people(org_id: str, audience: str) -> list[dict]:
    """[{user_id, email, email_on}] for 'approvers' or 'managers'."""
    return _client().rpc("notification_recipients", {"p_org": org_id, "p_audience": audience}).execute().data or []


def _inbox(org_id: str, user_ids: list[str], kind: str, title: str, body: str, path: str, campaign_id: str | None) -> None:
    _client().rpc("notify_users", {"p_org": org_id, "p_users": user_ids, "p_kind": kind, "p_title": title[:200], "p_body": body[:1000],
                                   "p_link": path, "p_campaign": campaign_id}).execute()


def _sender(org_id: str) -> dict | None:
    """The organisation's own Resend account, when it's connected live and not
    paused for bounces or complaints."""
    config = _client().rpc("email_sending_config", {"p_org": org_id}).execute().data
    if config and config.get("mode") == "live" and not config.get("paused_reason"):
        return {"api_key": config["api_key"], "from": config["from"], "reply_to": config.get("reply_to")}
    return None


def _deliver(org_id: str, audience: str, kind: str, title: str, text: str, path: str, *, campaign_id: str | None = None) -> int:
    """Tell everyone in the audience: in the app, by email (if they want it and
    email can go), and the organisation's Slack. Each channel fails on its own.
    Returns how many deliveries went out (in-app counts as one)."""
    link = _app_url(path)
    sent = 0
    try:
        people = _people(org_id, audience)
    except Exception as exc:
        logger.warning("notification recipients (%s) failed: %s", kind, exc)
        people = []
    try:
        if people:
            _inbox(org_id, [p["user_id"] for p in people], kind, title, text, path, campaign_id)
            sent += 1
    except Exception as exc:
        logger.warning("in-app notification (%s) failed: %s", kind, exc)
    try:
        webhook = _settings(org_id).get("slack_webhook_url")
        if webhook:
            requests.post(webhook, json={"text": f"{text}\n<{link}|Open in CampaignIQ>"}, timeout=10).raise_for_status()
            sent += 1
    except Exception as exc:
        logger.warning("slack notification (%s) failed: %s", kind, exc)
    to = [p["email"] for p in people if p.get("email_on", True) and p.get("email")]
    if to:
        try:
            sender = _sender(org_id)
            if sender or os.environ.get("NOTIFY_EMAIL", "false").lower() == "true":
                from src.tools.resend_client import send_email

                body = f"<p>{html.escape(text)}</p><p><a href=\"{html.escape(link, quote=True)}\">Open in CampaignIQ</a></p>"
                # One email per person: nobody sees the others' addresses, and one bad address doesn't stop the rest.
                for address in to:
                    try:
                        send_email([address], f"{PREFIX} {title}", body, sender=sender)
                        sent += 1
                    except Exception as exc:
                        logger.warning("email notification (%s) failed for one recipient: %s", kind, exc)
        except Exception as exc:
            logger.warning("email notification (%s) failed: %s", kind, exc)
    return sent


def notify_gate_opened(campaign_id: str, gate_number: int, round_number: int = 1) -> None:
    try:
        campaign = _campaign(campaign_id)
        required = _settings(campaign["org_id"]).get("required_approvals") or 1
        idea = campaign["idea"][:120]
        text = (
            f"Gate {gate_number} (round {round_number}) is waiting for approval: \"{idea}\". "
            f"{required} approval{'s' if required > 1 else ''} needed."
        )
        _deliver(campaign["org_id"], "approvers", "gate_opened", f"Approval needed: {idea[:60]}", text,
                 f"/campaigns/{campaign_id}", campaign_id=campaign_id)
    except Exception as exc:
        logger.warning("gate notification for %s failed: %s", campaign_id, exc)


def escalate_overdue_gates() -> int:
    """Notify managers about open gates past their organisation's deadline.
    Each gate is escalated once. Returns how many were escalated."""
    from datetime import datetime, timedelta, timezone

    client = _client()
    open_gates = (
        client.table("gate_decisions")
        .select("id,campaign_id,gate_number,round_number,created_at")
        .is_("decided_at", "null")
        .is_("escalated_at", "null")
        .execute()
        .data
    )
    now = datetime.now(timezone.utc)
    escalated = 0
    for gate in open_gates:
        try:
            campaign = _campaign(gate["campaign_id"])
            sla = _settings(campaign["org_id"]).get("approval_sla_hours")
            opened = datetime.fromisoformat(gate["created_at"])
            if not sla or now - opened < timedelta(hours=sla):
                continue
            hours = int((now - opened).total_seconds() // 3600)
            text = (
                f"Overdue: gate {gate['gate_number']} for \"{campaign['idea'][:120]}\" has waited {hours} h "
                f"(deadline {sla} h). The campaign is paused until it's decided."
            )
            _deliver(campaign["org_id"], "managers", "gate_overdue", "Approval overdue", text, f"/campaigns/{campaign['id']}",
                     campaign_id=campaign["id"])
            client.table("gate_decisions").update({"escalated_at": now.isoformat()}).eq("id", gate["id"]).execute()
            escalated += 1
        except Exception as exc:
            logger.warning("escalation for gate %s failed: %s", gate.get("id"), exc)
    return escalated


def notify_market_moment(campaign_id: str, kind: str, detail: dict) -> None:
    """A live campaign's topic just spiked (src/scheduler/market_watch.py)."""
    try:
        campaign = _campaign(campaign_id)
        keyword, idea = detail.get("keyword", ""), campaign["idea"][:120]
        if kind == "trend":
            what = f"Search interest in \"{keyword}\" jumped to {detail['value']}/100 (usually about {detail['baseline']})"
        else:
            what = f"News coverage of \"{keyword}\" jumped to {detail['value']} articles (was {detail['baseline']})"
            if detail.get("headline"):
                what += f". Latest: \"{detail['headline']}\""
        text = f"Market moment for \"{idea}\": {what}. A good time to run the next round."
        _deliver(campaign["org_id"], "approvers", "market_moment", f"Market moment: {idea[:60]}", text, f"/campaigns/{campaign_id}",
                 campaign_id=campaign_id)
    except Exception as exc:
        logger.warning("market moment notification for %s failed: %s", campaign_id, exc)


def notify_decision_reevaluated(campaign_id: str, before: str, after: str, score: int | None) -> None:
    """A campaign the decision engine said to WAIT on was re-checked because
    its trigger fired (src/scheduler/market_watch.py)."""
    try:
        campaign = _campaign(campaign_id)
        idea = campaign["idea"][:120]
        scored = f" (opportunity score {score})" if score is not None else ""
        text = (f"The decision engine re-checked \"{idea}\" now that interest has risen: "
                f"it moved from {before} to {after}{scored}. It's waiting for you at Gate 1.")
        _deliver(campaign["org_id"], "approvers", "decision_reevaluated", f"Re-evaluated: {after} for {idea[:50]}", text,
                 f"/campaigns/{campaign_id}", campaign_id=campaign_id)
    except Exception as exc:
        logger.warning("re-evaluation notification for %s failed: %s", campaign_id, exc)


TRIGGER_ADVICE = {
    "EXPIRED_OFFER": "Update or remove the offer in the ads, or extend the offer date, then resume.",
    "INVALID_DESTINATION": "Fix the landing page or change the link, then resume.",
    "POLICY_VIOLATION": "Edit the live copy so it no longer breaks the rule, then resume.",
    "REVOKED_APPROVAL": "Get the round approved again by someone who can approve, then resume.",
    "BRAND_RISK": "Check the news and decide whether the campaign should keep running; resume or mark it a false alarm.",
    "MANUAL_STOP": "Review the reason given and resume when it's safe.",
}


def notify_hold(campaign_id: str, trigger: str, detail: str, severity: str, *, waiting_sends: int = 0) -> None:
    """The circuit breaker paused a campaign (src/capabilities/circuit_breaker.py)."""
    try:
        campaign = _campaign(campaign_id)
        idea = campaign["idea"][:120]
        what = "Paused" if severity == "critical" else "Warning"
        text = (
            f"{what}: \"{idea}\". {detail} "
            f"{'Nothing more will be posted until an owner or admin resumes it. ' if severity == 'critical' else ''}"
            f"{f'{waiting_sends} send(s) are waiting. ' if waiting_sends else ''}"
            f"Already-published posts are not removed automatically. Suggested: {TRIGGER_ADVICE.get(trigger, 'Review it.')}"
        )
        _deliver(campaign["org_id"], "approvers" if severity != "critical" else "managers", "campaign_hold", f"{what}: {idea[:60]}",
                 text, f"/campaigns/{campaign_id}", campaign_id=campaign_id)
    except Exception as exc:
        logger.warning("hold notification for %s failed: %s", campaign_id, exc)


def notify_email_paused(org_id: str, reason: str) -> bool:
    """The email engine paused an organisation's campaign email (too many bounces
    or spam complaints: src/capabilities/email_engine.py). Tells its managers.
    Returns whether it reached anyone (if not, it's tried again next time)."""
    try:
        text = (f"Campaign email is paused: {reason}. Resend shuts accounts down past its limits, so nothing more "
                "goes out until an owner or admin looks at the recent bounces and complaints and resumes it.")
        return _deliver(org_id, "managers", "email_paused", "Campaign email paused", text, "/settings#email") > 0
    except Exception as exc:
        logger.warning("email pause notification for %s failed: %s", org_id, exc)
        return False
