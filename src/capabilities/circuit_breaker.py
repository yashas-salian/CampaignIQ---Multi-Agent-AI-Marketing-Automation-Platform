"""Brand reputation circuit breaker: stop a live campaign the moment it becomes unsafe.

Pre-publication checks (Gate 2, the crash test) can't see what changes after
launch. This module watches running campaigns and, on a critical condition,
places a hold (table campaign_holds, function place_hold()) that pauses the
campaign or one channel:

  EXPIRED_OFFER        the campaign's offer_ends_at has passed
  INVALID_DESTINATION  the call-to-action link now definitely fails (no such
                       host, 404/410); a timeout or 5xx is not enough
  POLICY_VIOLATION     the live copy now breaks a hard rule, e.g. a word the
                       brand kit banned after approval (rule checks, no LLM)
  REVOKED_APPROVAL     the round's Gate 2 approvals no longer reach the
                       organisation's quorum (an approver was removed or
                       downgraded), or an approver revoked it
  BRAND_RISK           crisis words (recall, lawsuit, boycott, ...) next to the
                       campaign's topic in at least two separate news
                       headlines; or a person pulled the emergency stop

Every rule is deterministic: thresholds, not an LLM, decide. Enforcement is in
the database: claim_delivery() refuses every send while a critical hold is
active, atomically, so a worker reading stale state can't slip past a pause.
Already-published posts stay up (they need their own deletion or correction).
Only an owner or admin resumes a campaign, with a written note
(resolve_hold()); held sends then go back to the retry queue.

Checks run in the hourly sweep (`python -m src.capabilities.circuit_breaker`),
right before each send (check_before_dispatch, cached briefly), and from the
daily market watch for brand-risk headlines.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("capabilities.circuit_breaker")

LIVE_STATUSES = ("awaiting_gate_1", "awaiting_gate_2", "awaiting_metrics", "awaiting_next_round", "created")
CRISIS_TERMS = (
    r"recall(s|ed)?", r"lawsuits?", r"sued", r"boycott(s|ed)?", r"scandals?", r"contaminat(ed|ion)", r"outbreak",
    r"data breach", r"hack(ed)?", r"fraud", r"investigat(ion|ed)", r"ban(ned)?", r"lay-?offs?", r"bankrupt(cy)?",
    r"outage", r"injur(y|ies|ed)", r"deaths?",
)
MIN_CRISIS_HEADLINES = 2  # one headline isn't verification; two separate ones are
DISPATCH_CACHE_SECONDS = 300


@dataclass
class Signal:
    trigger: str
    detail: str
    severity: str = "critical"
    channel: str | None = None
    evidence: dict = field(default_factory=dict)
    signal_at: str | None = None


# --- The checks (pure: data in, signals out) ---------------------------------------------------


def offer_expired(campaign: dict, now: datetime) -> Signal | None:
    ends = campaign.get("offer_ends_at")
    if not ends:
        return None
    ends_at = datetime.fromisoformat(str(ends).replace("Z", "+00:00"))
    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    if now < ends_at:
        return None
    return Signal("EXPIRED_OFFER", f"The offer ended on {ends_at:%d %b %Y %H:%M} UTC; the ads may still promise it.",
                  evidence={"offer_ends_at": ends_at.isoformat()}, signal_at=now.isoformat())


def destination_broken(campaign: dict, check) -> Signal | None:
    url = campaign.get("cta_url")
    if not url:
        return None
    result = check(url)
    if not result or result.get("status") != "invalid":
        return None
    return Signal("INVALID_DESTINATION", f"The ads link to {url}, which no longer works: {result.get('detail', '')}.",
                  evidence={"url": url, **result}, signal_at=datetime.now(timezone.utc).isoformat())


def policy_broken(copy_text: str, *, headline: str = "", cta: str = "", idea: str = "", domain_category: str = "other",
                  cta_url: str | None = None, banned_terms: list[str] | tuple = ()) -> Signal | None:
    """Hard rules only (banned words, personal data, a foreign link): things no
    approval reason can make acceptable once they're live."""
    from src.capabilities.crash_test import AdText, rule_checks

    if not copy_text:
        return None
    findings = [f for f in rule_checks(AdText(body=copy_text, headline=headline, cta=cta), idea=idea,
                                       domain_category=domain_category, cta_url=cta_url, banned_terms=banned_terms)
                if f.type == "POLICY_VIOLATION"]
    if not findings:
        return None
    return Signal("POLICY_VIOLATION", "The live ad now breaks a hard rule: " + " ".join(f.problem for f in findings[:3]),
                  evidence={"findings": [f.model_dump() for f in findings[:5]]}, signal_at=datetime.now(timezone.utc).isoformat())


def approvals_lapsed(votes: list[dict], member_roles: dict[str, str], required: int) -> Signal | None:
    """The round's approve/edit votes whose voters can still approve, against the quorum."""
    approving = [v for v in votes if v.get("decision") in ("approve", "edit")]
    if not approving:
        return None
    valid = [v for v in approving if member_roles.get(v["user_id"]) in ("owner", "admin", "approver")]
    if len(valid) >= max(1, required):
        return None
    lapsed = [v["user_id"] for v in approving if v not in valid]
    return Signal("REVOKED_APPROVAL",
                  f"The live round was approved by {len(approving)} person(s); {len(lapsed)} can no longer approve "
                  f"(removed or role changed), leaving {len(valid)} of the {required} required.",
                  evidence={"lapsed_approvers": lapsed, "valid": len(valid), "required": required},
                  signal_at=datetime.now(timezone.utc).isoformat())


def brand_risk(keyword: str, headlines: list[str], *, fetched_at: str | None = None) -> Signal | None:
    """Crisis words next to the campaign's topic in at least two separate headlines."""
    if not keyword or not headlines:
        return None
    topic = [w for w in re.findall(r"\w+", keyword.lower()) if len(w) > 2]
    if not topic:
        return None
    crisis = re.compile(r"\b(" + "|".join(CRISIS_TERMS) + r")\b", re.IGNORECASE)
    hits = []
    for h in dict.fromkeys(str(x).strip() for x in headlines if x):  # duplicates don't count twice
        low = h.lower()
        if crisis.search(h) and sum(1 for w in topic if w in low) >= min(2, len(topic)):
            hits.append(h)
    if len(hits) < MIN_CRISIS_HEADLINES:
        return None
    return Signal("BRAND_RISK", f"{len(hits)} news headlines link “{keyword}” with a crisis: “{hits[0]}”.",
                  evidence={"keyword": keyword, "headlines": hits[:5]}, signal_at=fetched_at or datetime.now(timezone.utc).isoformat())


# --- Evaluating a campaign (I/O) ------------------------------------------------------------------


def _client():
    from src.db.supabase_client import get_client

    return get_client()


def _live_round(campaign_id: str, round_number: int) -> dict:
    row = (_client().table("iterations").select("copy_text,headline,cta,round_number")
           .eq("campaign_id", campaign_id).eq("round_number", round_number).maybe_single().execute())
    return (row.data if row else None) or {}


def _round_votes(campaign_id: str, round_number: int) -> list[dict]:
    gate = (_client().table("gate_decisions").select("id,decided_at").eq("campaign_id", campaign_id)
            .eq("gate_number", 2).eq("round_number", round_number).maybe_single().execute())
    gate = gate.data if gate else None
    if not gate or not gate.get("decided_at"):
        return []
    return _client().table("gate_approvals").select("user_id,decision").eq("gate_decision_id", gate["id"]).execute().data or []


def gather(campaign: dict, *, check=None, now: datetime | None = None) -> list[Signal]:
    """Every deterministic check for one campaign (brand-risk news comes from the market watch)."""
    from src.capabilities.brand import brand_kit_for_campaign
    from src.capabilities.decision import check_destination

    now = now or datetime.now(timezone.utc)
    signals: list[Signal] = []
    expired = offer_expired(campaign, now)
    if expired:
        signals.append(expired)
    broken = destination_broken(campaign, check or check_destination)
    if broken:
        signals.append(broken)
    # The copy and approvals of the round that's live (approved at Gate 2) or about to be.
    if campaign.get("status") in ("awaiting_metrics", "awaiting_next_round", "awaiting_gate_2"):
        it = _live_round(campaign["id"], int(campaign.get("current_round") or 1))
        kit = brand_kit_for_campaign(campaign["id"])
        policy = policy_broken(
            it.get("copy_text") or "", headline=it.get("headline") or "", cta=it.get("cta") or "",
            idea=campaign.get("idea") or "", domain_category=campaign.get("domain_category") or "other",
            cta_url=campaign.get("cta_url"), banned_terms=kit.forbidden_words if kit else (),
        )
        if policy:
            signals.append(policy)
        if campaign.get("status") != "awaiting_gate_2":
            votes = _round_votes(campaign["id"], int(campaign.get("current_round") or 1))
            if votes:
                members = _client().table("memberships").select("user_id,role").eq("org_id", campaign["org_id"]).execute().data or []
                policy_row = _client().rpc("org_approval_policy", {"p_org": campaign["org_id"]}).execute().data or {}
                lapsed = approvals_lapsed(votes, {m["user_id"]: m["role"] for m in members},
                                          int(policy_row.get("required_approvals") or 1))
                if lapsed:
                    signals.append(lapsed)
    return signals


def place(campaign: dict, signal: Signal) -> str | None:
    """Store the hold (idempotent per trigger and channel) and tell the approvers. Never raises."""
    try:
        existing = (_client().table("campaign_holds").select("id").eq("campaign_id", campaign["id"])
                    .eq("trigger", signal.trigger).eq("status", "active").execute().data or [])
        hold_id = _client().rpc("place_hold", {
            "p_campaign": campaign["id"], "p_trigger": signal.trigger, "p_severity": signal.severity,
            "p_detail": signal.detail, "p_evidence": signal.evidence, "p_channel": signal.channel,
            "p_signal_at": signal.signal_at,
        }).execute().data
        if not existing:  # a new hold, not a re-check of one already in place
            _notify(campaign, signal)
        return hold_id
    except Exception as exc:
        logger.warning("placing a %s hold on %s failed: %s", signal.trigger, campaign.get("id"), exc)
        return None


def _notify(campaign: dict, signal: Signal) -> None:
    try:
        from src.notifications import notify_hold

        held = (_client().table("deliveries").select("id").eq("campaign_id", campaign["id"])
                .in_("status", ["pending", "failed", "held"]).execute().data or [])
        notify_hold(campaign["id"], signal.trigger, signal.detail, signal.severity, waiting_sends=len(held))
    except Exception as exc:
        logger.warning("hold notification for %s failed: %s", campaign.get("id"), exc)


def evaluate_campaign(campaign_id: str, *, check=None, now: datetime | None = None) -> list[Signal]:
    from src.db.supabase_client import get_campaign

    campaign = get_campaign(campaign_id)
    if campaign.get("status") not in LIVE_STATUSES:
        return []
    signals = gather(campaign, check=check, now=now)
    for s in signals:
        place(campaign, s)
    return signals


_recent: dict[str, float] = {}


def check_before_dispatch(campaign_id: str) -> None:
    """Right before a send: re-run the checks (at most every few minutes per
    campaign, so a round's three channels don't fetch the link three times).
    Whatever it finds becomes a hold that claim_delivery() then enforces.
    Best effort: the database refusal is the guarantee, not this."""
    now = time.monotonic()
    if now - _recent.get(campaign_id, 0) < DISPATCH_CACHE_SECONDS:
        return
    _recent[campaign_id] = now
    try:
        evaluate_campaign(campaign_id)
    except Exception as exc:
        logger.warning("pre-send circuit check for %s failed: %s", campaign_id, exc)


def sweep(now: datetime | None = None) -> int:
    """Hourly: every live campaign. Returns how many signals were found."""
    rows = (_client().table("campaigns").select("id").in_("status", list(LIVE_STATUSES)).execute().data or [])
    found = 0
    for row in rows:
        try:
            found += len(evaluate_campaign(row["id"], now=now))
        except Exception as exc:  # one campaign's failure never stops the sweep
            logger.warning("circuit check for %s failed: %s", row["id"], exc)
    return found


def check_news(campaign: dict, keyword: str, news: dict | None) -> Signal | None:
    """Called by the market watch with the headlines it just fetched."""
    if not news or news.get("error"):
        return None
    signal = brand_risk(keyword, news.get("headlines") or [], fetched_at=news.get("fetched_at"))
    if signal and campaign.get("status") in LIVE_STATUSES:
        place(campaign, signal)
    return signal


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    print(f"Circuit breaker: {sweep()} signal(s) across live campaigns.")
