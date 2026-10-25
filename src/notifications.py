"""Approval notifications: tell approvers a gate is waiting, escalate overdue ones.

Channels, per organisation:
  * Slack: org_settings.slack_webhook_url (a Slack incoming webhook; free).
  * Email (Resend): opt-in with NOTIFY_EMAIL=true, since the free Resend tier
    only delivers to the account's own address until a domain is verified.
Links point at APP_BASE_URL (the deployed frontend). Approving happens in the
app, signed in, so the quorum and role rules always apply.
A notification can never fail a campaign run: every error is logged and dropped.
"""
import html
import logging
import os

import requests

logger = logging.getLogger("notifications")

APPROVER_ROLES = ("owner", "admin", "approver")
MANAGER_ROLES = ("owner", "admin")


def _app_url(path: str) -> str:
    base = os.environ.get("APP_BASE_URL", "https://campaign-iq-multi-agent-ai-marketin.vercel.app").rstrip("/")
    return f"{base}{path}"


def _org_context(campaign_id: str) -> tuple[dict, dict, list[dict]]:
    from src.db.supabase_client import get_client

    client = get_client()
    campaign = client.table("campaigns").select("id,idea,org_id,user_id").eq("id", campaign_id).single().execute().data
    settings = (
        client.table("org_settings").select("*").eq("org_id", campaign["org_id"]).maybe_single().execute()
    )
    members = client.rpc("org_members", {"p_org": campaign["org_id"]}).execute().data or []
    return campaign, (settings.data if settings and settings.data else {}), members


def _send(settings: dict, recipients: list[str], subject: str, text: str, link: str) -> None:
    webhook = settings.get("slack_webhook_url")
    if webhook:
        try:
            requests.post(webhook, json={"text": f"{text}\n<{link}|Open in MarketingOS>"}, timeout=10).raise_for_status()
        except Exception as exc:
            logger.warning("slack notification failed: %s", exc)
    if recipients and os.environ.get("NOTIFY_EMAIL", "false").lower() == "true":
        try:
            from src.tools.resend_client import send_email

            send_email(recipients, subject, f"<p>{html.escape(text)}</p><p><a href=\"{link}\">Open in MarketingOS</a></p>")
        except Exception as exc:
            logger.warning("email notification failed: %s", exc)


def notify_gate_opened(campaign_id: str, gate_number: int, round_number: int = 1) -> None:
    try:
        campaign, settings, members = _org_context(campaign_id)
        required = settings.get("required_approvals") or 1
        recipients = [m["email"] for m in members if m["role"] in APPROVER_ROLES and m.get("email")]
        idea = campaign["idea"][:120]
        text = (
            f"Gate {gate_number} (round {round_number}) is waiting for approval: \"{idea}\". "
            f"{required} approval{'s' if required > 1 else ''} needed."
        )
        _send(settings, recipients, f"[MarketingOS] Approval needed: {idea[:60]}", text, _app_url(f"/campaigns/{campaign_id}"))
    except Exception as exc:
        logger.warning("gate notification for %s failed: %s", campaign_id, exc)


def escalate_overdue_gates() -> int:
    """Notify managers about open gates past their organisation's deadline.
    Each gate is escalated once. Returns how many were escalated."""
    from datetime import datetime, timedelta, timezone

    from src.db.supabase_client import get_client

    client = get_client()
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
            campaign, settings, members = _org_context(gate["campaign_id"])
            sla = settings.get("approval_sla_hours")
            opened = datetime.fromisoformat(gate["created_at"])
            if not sla or now - opened < timedelta(hours=sla):
                continue
            recipients = [m["email"] for m in members if m["role"] in MANAGER_ROLES and m.get("email")]
            hours = int((now - opened).total_seconds() // 3600)
            text = (
                f"Overdue: gate {gate['gate_number']} for \"{campaign['idea'][:120]}\" has waited {hours} h "
                f"(deadline {sla} h). The campaign is paused until it's decided."
            )
            _send(settings, recipients, "[MarketingOS] Approval overdue", text, _app_url(f"/campaigns/{campaign['id']}"))
            client.table("gate_decisions").update({"escalated_at": now.isoformat()}).eq("id", gate["id"]).execute()
            escalated += 1
        except Exception as exc:
            logger.warning("escalation for gate %s failed: %s", gate.get("id"), exc)
    return escalated


def notify_market_moment(campaign_id: str, kind: str, detail: dict) -> None:
    """A live campaign's topic just spiked (src/scheduler/market_watch.py)."""
    try:
        campaign, settings, members = _org_context(campaign_id)
        recipients = [m["email"] for m in members if m["role"] in APPROVER_ROLES and m.get("email")]
        keyword, idea = detail.get("keyword", ""), campaign["idea"][:120]
        if kind == "trend":
            what = f"Search interest in \"{keyword}\" jumped to {detail['value']}/100 (usually about {detail['baseline']})"
        else:
            what = f"News coverage of \"{keyword}\" jumped to {detail['value']} articles (was {detail['baseline']})"
            if detail.get("headline"):
                what += f". Latest: \"{detail['headline']}\""
        text = f"Market moment for \"{idea}\": {what}. A good time to run the next round."
        _send(settings, recipients, f"[MarketingOS] Market moment: {idea[:60]}", text, _app_url(f"/campaigns/{campaign_id}"))
    except Exception as exc:
        logger.warning("market moment notification for %s failed: %s", campaign_id, exc)


def notify_decision_reevaluated(campaign_id: str, before: str, after: str, score: int | None) -> None:
    """A campaign the decision engine said to WAIT on was re-checked because
    its trigger fired (src/scheduler/market_watch.py)."""
    try:
        campaign, settings, members = _org_context(campaign_id)
        recipients = [m["email"] for m in members if m["role"] in APPROVER_ROLES and m.get("email")]
        idea = campaign["idea"][:120]
        scored = f" (opportunity score {score})" if score is not None else ""
        text = (f"The decision engine re-checked \"{idea}\" now that interest has risen: "
                f"it moved from {before} to {after}{scored}. It's waiting for you at Gate 1.")
        _send(settings, recipients, f"[MarketingOS] Re-evaluated: {after} for {idea[:50]}", text,
              _app_url(f"/campaigns/{campaign_id}"))
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
        campaign, settings, members = _org_context(campaign_id)
        recipients = [m["email"] for m in members if m["role"] in APPROVER_ROLES and m.get("email")]
        idea = campaign["idea"][:120]
        what = "Paused" if severity == "critical" else "Warning"
        text = (
            f"{what}: \"{idea}\". {detail} "
            f"{'Nothing more will be posted until an owner or admin resumes it. ' if severity == 'critical' else ''}"
            f"{f'{waiting_sends} send(s) are waiting. ' if waiting_sends else ''}"
            f"Already-published posts are not removed automatically. Suggested: {TRIGGER_ADVICE.get(trigger, 'Review it.')}"
        )
        _send(settings, recipients, f"[MarketingOS] {what}: {idea[:60]}", text, _app_url(f"/campaigns/{campaign_id}"))
    except Exception as exc:
        logger.warning("hold notification for %s failed: %s", campaign_id, exc)
