"""Decision intelligence: should this campaign run at all? (the "anti-marketing" engine)

A feasible idea isn't automatically a good investment: a topic can be popular
without anyone wanting to buy, crowded with competitors, or unreachable on the
channels we post to. Before any creative is made, this engine reads the
evidence gathered so far and recommends one of five outcomes:

  LAUNCH                 strong, well-evidenced opportunity
  TEST_SMALL             worth trying, but cap the scope (fewer rounds)
  WAIT                   demand is low now but clearly rising: re-check later
  KILL                   weak opportunity (soft: a human may still approve with
                         a reason) or a hard block (never runs)
  INSUFFICIENT_EVIDENCE  too little or too stale evidence to judge

Design rules:
  * Deterministic, no LLM: the same inputs and policy version always give the
    same decision, so every recommendation can be reproduced and audited.
    `evaluate()` is pure; `gather_inputs()` does the I/O.
  * Hard constraints first (prohibited product, banned words, claims that
    can't be substantiated, a broken destination). A high opportunity score
    never overrides them.
  * Six weighted factors (a short scorecard: long ones pull every score to
    the middle). Each records its source, when it was fetched, whether it's
    fresh, and how reliable it is: "measured", "proxy" (an indirect stand-in,
    e.g. news volume for competitive saturation) or "estimate" (simulated
    personas). Missing or stale factors are left out of the score and raise
    the uncertainty instead of counting as zero.
  * A human still approves at Gate 1: the engine recommends, it doesn't decide
    (except hard blocks).
  * The decision, its inputs snapshot and the policy version are stored
    (campaign_decisions), and the campaign's eventual outcome is written back
    at the end, so recommendations can be checked against results.
"""
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

logger = logging.getLogger("capabilities.decision")

POLICY_VERSION = "decision-v1"
DECISIONS = ("LAUNCH", "TEST_SMALL", "WAIT", "KILL", "INSUFFICIENT_EVIDENCE")

# Scorecard weights (sum to 1).
WEIGHTS = {
    "demand": 0.25,
    "momentum": 0.10,
    "purchase_intent": 0.20,
    "competition": 0.15,
    "reachability": 0.15,
    "track_record": 0.15,
}
STALE_AFTER = timedelta(hours=72)
LAUNCH_SCORE, TEST_SCORE = 65, 40
MAX_LAUNCH_UNCERTAINTY = 0.35
MAX_UNCERTAINTY = 0.5  # above this, no recommendation beyond "insufficient evidence"
TEST_SMALL_MAX_ROUNDS = 2
MIN_INTENT_TEXTS = 5
MIN_HISTORY_CAMPAIGNS = 2
STRONG, WEAK = 0.65, 0.35

# --- Hard constraints ---------------------------------------------------------

# Products the major ad platforms (Meta, Google) don't allow advertising at all.
_PROHIBITED_PRODUCTS = [
    (r"\b(cocaine|heroin|meth(amphetamine)?|mdma|ecstasy|lsd)\b", "illegal drugs"),
    # Not the toys and tools that share the word (water guns, glue guns, massage guns...).
    (r"(?<!water )(?<!glue )(?<!toy )(?<!nerf )(?<!massage )(?<!heat )(?<!nail )(?<!staple )(?<!spray )(?<!paint )"
     r"\b(guns?|firearms?|rifles?|pistols?|ammunition|ammo|explosives?)\b", "weapons or ammunition"),
    (r"\b(counterfeit|replica|knock-?off|fake) (designer|brand(ed)?|watches|bags|handbags|sneakers|goods)\b", "counterfeit goods"),
    (r"\bfake (id|ids|passports?|documents?|degrees?|diplomas?)\b", "fake documents"),
    (r"\b(spyware|stalkerware|keyloggers?|phone hacking|hack (into|someone))\b", "spyware or hacking"),
    (r"\b(escort|porn|pornograph(y|ic)|adult (content|videos?))\b", "adult content"),
]
# Claims no evidence could support in an ad: blocked outright at the idea stage.
_UNSUPPORTABLE_CLAIMS = [
    r"\bcures?\b.{0,30}\b(cancer|diabetes|covid|hiv|aids|alzheimer'?s|autism|arthritis)\b",
    r"\b(cancer|diabetes|covid|hiv|aids|alzheimer'?s|autism|arthritis)\b.{0,30}\bcure\b",
    r"\bguaranteed (returns?|profits?|income|gains?)\b",
    r"\b(double|triple) your (money|investment)\b",
    r"\brisk[- ]free (investment|returns?|profits?)\b",
    r"\blose \d+\s?(kg|kilos|lbs?|pounds) in \d+\s?(days?|weeks?)\b",
]

# --- Purchase intent ------------------------------------------------------------

# Transactional terms (ready to buy) count fully, commercial ones (comparing) at 0.6.
_INTENT_TERMS = {
    "en": ([r"\bbuy(ing)?\b", r"\border(ed|ing)?\b", r"\bpurchas(e|ed|ing)\b", r"\bdiscount\b", r"\bcoupon\b", r"\bdeal\b",
            r"\bshop(ping)?\b", r"\bsubscri(be|ption)\b", r"\bpre-?order\b", r"\bfree (trial|shipping|delivery)\b"],
           [r"\bbest\b", r"\breview(s)?\b", r"\bvs\.?\b", r"\bcompar(e|ison)\b", r"\bprice(s|d)?\b", r"\bpricing\b",
            r"\bcost(s)?\b", r"\bcheap(er|est)?\b", r"\brecommend(ation|ed)?s?\b", r"\bworth it\b"]),
    "es": ([r"\bcomprar\b", r"\bpedido\b", r"\bdescuento\b", r"\boferta\b", r"\bsuscri"], [r"\bmejor(es)?\b", r"\bprecio\b", r"\breseña", r"\bcomparar\b"]),
    "fr": ([r"\bacheter\b", r"\bcommande(r)?\b", r"\bréduction\b", r"\bpromo\b", r"\babonnement\b"], [r"\bmeilleur", r"\bprix\b", r"\bavis\b", r"\bcompar"]),
    "pt": ([r"\bcomprar\b", r"\bpedido\b", r"\bdesconto\b", r"\bpromoção\b", r"\bassinatura\b"], [r"\bmelhor(es)?\b", r"\bpreço\b", r"\bavaliaç", r"\bcompar"]),
    "hi": ([r"खरीद", r"ऑर्डर", r"छूट", r"ऑफ़र"], [r"सबसे अच्छा", r"कीमत", r"रिव्यू", r"तुलना"]),
}

# --- Reachability ---------------------------------------------------------------

_CHANNEL_WORDS = {
    "email": ("email", "e-mail", "newsletter", "inbox"),
    "bluesky": ("bluesky", "twitter", "x.com", "threads", "microblog"),
    "mastodon": ("mastodon", "fediverse"),
    "reddit": ("reddit", "forum"),
}


class Factor(BaseModel):
    key: str
    weight: float
    score: float | None  # 0-1; None when missing or stale
    value: str  # the observed value, human-readable
    source: str
    reliability: str  # measured | proxy | estimate
    fetched_at: str | None = None
    available: bool = True
    stale: bool = False
    note: str = ""


class Decision(BaseModel):
    decision: str
    opportunity_score: int | None
    uncertainty: float
    reason_codes: list[str]
    factors: list[Factor]
    hard_blocks: list[dict] = []
    review_flags: list[dict] = []
    constraints: dict = {}
    reevaluate: dict | None = None
    requires_human_approval: bool = True
    policy_version: str = POLICY_VERSION
    baseline: dict = {}
    evaluated_at: str


@dataclass
class DecisionInputs:
    idea: str
    domain_category: str = "other"
    target_language: str = "en"
    feasibility_score: int | None = None
    keyword: str = ""
    trend: dict | None = None  # get_trend_interest() + fetched_at
    news: dict | None = None  # get_news_volume() + fetched_at
    community: list[dict] = field(default_factory=list)  # search_bluesky/mastodon() + texts + fetched_at
    personas: list[dict] = field(default_factory=list)  # {"channel_fit": ...}
    active_channels: list[str] = field(default_factory=lambda: ["bluesky", "email"])
    history: dict | None = None  # {"campaigns": n, "mean_reward": x}
    cta_url: str | None = None
    destination: dict | None = None  # {"status": ok|invalid|unverified, "detail": ...}
    banned_terms: list[str] = field(default_factory=list)
    # Recent moves by tracked competitors in this market (competitors.recent_activity):
    # review flags for the approver, never part of the score.
    competitor_activity: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        """What the decision was made from (texts trimmed), for reproducing it later."""
        return {
            "idea": self.idea, "domain_category": self.domain_category, "target_language": self.target_language,
            "feasibility_score": self.feasibility_score, "keyword": self.keyword,
            "trend": self.trend, "news": {k: v for k, v in (self.news or {}).items() if k != "headlines"} | {
                "headlines": (self.news or {}).get("headlines", [])[:10]} if self.news else None,
            "community": [{k: (v[:10] if k == "texts" else v) for k, v in c.items()} for c in self.community],
            "personas": [{"channel_fit": p.get("channel_fit", "")} for p in self.personas],
            "active_channels": self.active_channels, "history": self.history, "cta_url": self.cta_url,
            "destination": self.destination, "banned_terms_count": len(self.banned_terms),
            "competitor_activity": self.competitor_activity[:5],
        }


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _parse_time(value) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _stale(fetched_at, now: datetime) -> bool:
    t = _parse_time(fetched_at)
    return t is not None and now - t > STALE_AFTER


def _failed(signal: dict | None) -> bool:
    return not signal or bool(signal.get("error")) or bool(signal.get("rate_limited"))


# --- Factors ----------------------------------------------------------------------


def _demand(i: DecisionInputs, now: datetime) -> tuple[Factor, Factor]:
    t = i.trend
    if _failed(t) or (t or {}).get("no_data"):
        reason = ("rate-limited" if t and t.get("rate_limited")
                  else "has too little data for this phrase" if t and t.get("no_data") else "unavailable")
        missing = dict(score=None, available=False, value=f"Google Trends {reason}", source="Google Trends",
                       reliability="measured", fetched_at=(t or {}).get("fetched_at"))
        return Factor(key="demand", weight=WEIGHTS["demand"], **missing), Factor(key="momentum", weight=WEIGHTS["momentum"], **missing)
    mean, latest = float(t.get("mean_interest") or 0), float(t.get("latest_interest") or 0)
    stale = _stale(t.get("fetched_at"), now)
    demand = _clamp((0.6 * latest + 0.4 * mean) / 60)
    ratio = latest / max(mean, 1.0)
    momentum = _clamp((ratio - 0.5) / 1.5)
    common = dict(source="Google Trends", reliability="measured", fetched_at=t.get("fetched_at"), stale=stale)
    return (
        Factor(key="demand", weight=WEIGHTS["demand"], score=None if stale else round(demand, 3),
               value=f"search interest {round(latest)} now, {round(mean)} on average (0-100)", **common),
        Factor(key="momentum", weight=WEIGHTS["momentum"], score=None if stale else round(momentum, 3),
               value=f"latest is {ratio:.1f}× the average" + (", rising" if t.get("trending_up") else ""), **common),
    )


def intent_share(texts: list[str], language: str) -> float:
    """Share of texts that read as buying (1) or comparing (0.6)."""
    transactional, commercial = _INTENT_TERMS.get(language, _INTENT_TERMS["en"])
    total = 0.0
    for text in texts:
        low = text.lower()
        if any(re.search(p, low) for p in transactional):
            total += 1.0
        elif any(re.search(p, low) for p in commercial):
            total += 0.6
    return total / len(texts) if texts else 0.0


def _purchase_intent(i: DecisionInputs, now: datetime) -> Factor:
    texts, sources, times = [], [], []
    if i.news and not _failed(i.news):
        texts += [str(h) for h in i.news.get("headlines") or []]
        sources.append("news headlines")
        times.append(i.news.get("fetched_at"))
    for c in i.community:
        if not _failed(c):
            texts += [str(t) for t in c.get("texts") or []]
            sources.append(c.get("source", "community posts"))
            times.append(c.get("fetched_at"))
    source = " + ".join(sources) or "news and community search"
    fetched = max((t for t in times if t), default=None)
    if len(texts) < MIN_INTENT_TEXTS:
        return Factor(key="purchase_intent", weight=WEIGHTS["purchase_intent"], score=None, available=False,
                      value=f"only {len(texts)} posts/headlines found (need {MIN_INTENT_TEXTS})", source=source,
                      reliability="proxy", fetched_at=fetched)
    stale = all(_stale(t, now) for t in times if t) and any(times)
    share = intent_share(texts, i.target_language)
    return Factor(key="purchase_intent", weight=WEIGHTS["purchase_intent"], score=None if stale else round(_clamp(share / 0.3), 3),
                  value=f"{round(share * 100)}% of {len(texts)} posts/headlines talk about buying or comparing",
                  source=source, reliability="proxy", fetched_at=fetched, stale=stale,
                  note="Keyword match on buying/comparing words; a stand-in for real purchase-intent data.")


def _competition(i: DecisionInputs, now: datetime) -> Factor:
    n = i.news
    if _failed(n):
        return Factor(key="competition", weight=WEIGHTS["competition"], score=None, available=False,
                      value="news search unavailable", source="NewsAPI", reliability="proxy",
                      fetched_at=(n or {}).get("fetched_at"))
    total = int(n.get("total_results") or 0)
    saturation = _clamp(math.log10(1 + total) / math.log10(1 + 2000))
    stale = _stale(n.get("fetched_at"), now)
    return Factor(key="competition", weight=WEIGHTS["competition"], score=None if stale else round(1 - saturation, 3),
                  value=f"{total} recent news articles on the topic", source="NewsAPI", reliability="proxy",
                  fetched_at=n.get("fetched_at"), stale=stale,
                  note="Coverage volume as a stand-in for how crowded the market is (no ad-spend data).")


def reachable(channel_fit: str, channels: list[str]) -> bool:
    text = f" {channel_fit.lower()} "
    return any(word in text for c in channels for word in _CHANNEL_WORDS.get(c, (c,)))


def _reachability(i: DecisionInputs) -> Factor:
    if not i.personas:
        return Factor(key="reachability", weight=WEIGHTS["reachability"], score=None, available=False,
                      value="no audience personas yet", source="AI personas", reliability="estimate")
    hits = sum(1 for p in i.personas if reachable(str(p.get("channel_fit", "")), i.active_channels))
    return Factor(key="reachability", weight=WEIGHTS["reachability"], score=round(hits / len(i.personas), 3),
                  value=f"{hits} of {len(i.personas)} personas use a channel we post to ({', '.join(i.active_channels)})",
                  source="AI personas", reliability="estimate",
                  note="Simulated personas, not observed customers.")


def _track_record(i: DecisionInputs) -> Factor:
    h = i.history or {}
    n = int(h.get("campaigns") or 0)
    if n < MIN_HISTORY_CAMPAIGNS or h.get("mean_reward") is None:
        return Factor(key="track_record", weight=WEIGHTS["track_record"], score=None, available=False,
                      value=f"{n} measured past campaign(s) in this category (need {MIN_HISTORY_CAMPAIGNS})",
                      source="your campaign history", reliability="measured")
    mean = float(h["mean_reward"])
    return Factor(key="track_record", weight=WEIGHTS["track_record"], score=round(_clamp(mean / 0.15), 3),
                  value=f"average reward {mean:.2f} over {n} past campaigns in this category",
                  source="your campaign history", reliability="measured",
                  note="Engagement rewards, a proxy for business results.")


# --- Hard constraints -------------------------------------------------------------


def hard_blocks(i: DecisionInputs) -> tuple[list[dict], list[dict]]:
    """(blocks, review flags). Blocks stop the campaign whatever the score."""
    from src.capabilities.guardrails import _ABSOLUTE_CLAIMS, _REGULATED_CLAIMS, _banned_terms

    text = i.idea.lower()
    blocks: list[dict] = []
    for pattern, what in _PROHIBITED_PRODUCTS:
        found = re.search(pattern, text)
        if found:
            blocks.append({"code": "PROHIBITED_PRODUCT", "detail": f'"{found.group(0)}": ad platforms don\'t allow advertising {what}'})
    for term in _banned_terms(i.banned_terms):
        if re.search(rf"\b{re.escape(term)}\b", text):
            blocks.append({"code": "BANNED_TERM", "detail": f'"{term}" is on the banned list'})
    for pattern in _UNSUPPORTABLE_CLAIMS:
        found = re.search(pattern, text)
        if found:
            blocks.append({"code": "UNSUPPORTABLE_CLAIM", "detail": f'"{found.group(0)}" can\'t be substantiated in an ad'})
    if i.destination and i.destination.get("status") == "invalid":
        blocks.append({"code": "INVALID_DESTINATION", "detail": i.destination.get("detail") or "the link doesn't work"})
    flags = []
    for pattern in _ABSOLUTE_CLAIMS + _REGULATED_CLAIMS.get(i.domain_category, []):
        found = re.search(pattern, text)
        if found and not any(found.group(0) in b["detail"] for b in blocks):
            flags.append({"code": "CLAIM_NEEDS_EVIDENCE", "detail": f'"{found.group(0)}" will need evidence before it appears in an ad'})
    for move in i.competitor_activity[:3]:
        flags.append({"code": "COMPETITOR_MOVE", "detail": f"{move.get('competitor') or 'A competitor'}: {move.get('summary', '')}"[:300],
                      "kind": move.get("kind"), "url": move.get("url"), "observed_at": move.get("observed_at")})
    return blocks, flags


# --- The policy -------------------------------------------------------------------


def evaluate(i: DecisionInputs, *, now: datetime | None = None) -> Decision:
    now = now or datetime.now(timezone.utc)
    demand, momentum = _demand(i, now)
    factors = [demand, momentum, _purchase_intent(i, now), _competition(i, now), _reachability(i), _track_record(i)]
    used = [f for f in factors if f.score is not None]
    weight = sum(f.weight for f in used)
    uncertainty = round(1 - weight, 3)
    # A score from a sliver of the evidence would look precise and mean nothing: none at all.
    score = round(100 * sum(f.weight * f.score for f in used) / weight) if weight and uncertainty <= MAX_UNCERTAINTY else None
    blocks, flags = hard_blocks(i)
    by_key = {f.key: f for f in factors}

    reasons: list[str] = []
    for f in factors:
        if f.stale:
            reasons.append("STALE_EVIDENCE")
    labels = {
        "demand": ("STRONG_DEMAND", "WEAK_DEMAND"), "purchase_intent": ("STRONG_PURCHASE_INTENT", "WEAK_PURCHASE_INTENT"),
        "competition": ("LOW_COMPETITION", "HIGH_COMPETITOR_SATURATION"), "reachability": ("AUDIENCE_REACHABLE", "AUDIENCE_HARD_TO_REACH"),
        "track_record": ("PROVEN_IN_CATEGORY", "POOR_TRACK_RECORD"), "momentum": ("RISING_INTEREST", "FALLING_INTEREST"),
    }
    missing = {"demand": "MISSING_DEMAND_DATA", "purchase_intent": "MISSING_INTENT_DATA", "competition": "MISSING_COMPETITION_DATA",
               "reachability": "MISSING_AUDIENCE", "track_record": "NO_HISTORY", "momentum": None}
    for key, (good, bad) in labels.items():
        f = by_key[key]
        if f.score is None:
            if not f.stale and missing[key]:
                reasons.append(missing[key])
        elif f.score >= STRONG:
            reasons.append(good)
        elif f.score <= WEAK:
            reasons.append(bad)
    if i.destination and i.destination.get("status") == "unverified":
        reasons.append("DESTINATION_UNVERIFIED")
    reasons = list(dict.fromkeys(reasons))

    constraints: dict = {}
    reevaluate = None
    if blocks:
        decision = "KILL"
        reasons = list(dict.fromkeys([b["code"] for b in blocks] + reasons))
    elif uncertainty > MAX_UNCERTAINTY or (demand.score is None and by_key["purchase_intent"].score is None):
        decision = "INSUFFICIENT_EVIDENCE"
    elif (momentum.score is not None and momentum.score >= 0.75 and demand.score is not None
          and demand.score < WEAK and score is not None and score < 55):
        decision = "WAIT"
        mean = float((i.trend or {}).get("mean_interest") or 0)
        reevaluate = {"type": "trend_threshold", "keyword": i.keyword, "threshold": max(30, round(mean * 1.5)),
                      "detail": "Re-check when search interest reaches this level (the daily market watch does it)."}
    elif (score is not None and score >= LAUNCH_SCORE and uncertainty <= MAX_LAUNCH_UNCERTAINTY
          # A full launch needs measured demand and no red flag on the three market
          # factors: a crowded market, or a popular topic nobody buys in, is a test.
          and demand.score is not None
          and all(by_key[k].score is None or by_key[k].score > WEAK for k in ("demand", "purchase_intent", "competition"))):
        decision = "LAUNCH"
    elif score is not None and score >= TEST_SCORE:
        decision = "TEST_SMALL"
        constraints = {"max_rounds": TEST_SMALL_MAX_ROUNDS}
    else:
        decision = "KILL"

    baseline = {
        "rule": "launch whenever feasibility ≥ 40",
        "decision": None if i.feasibility_score is None else ("LAUNCH" if i.feasibility_score >= 40 else "KILL"),
    }
    return Decision(
        decision=decision, opportunity_score=score, uncertainty=uncertainty, reason_codes=reasons, factors=factors,
        hard_blocks=blocks, review_flags=flags, constraints=constraints, reevaluate=reevaluate,
        requires_human_approval=True, baseline=baseline, evaluated_at=now.isoformat(),
    )


# --- Gathering the evidence (I/O) ---------------------------------------------------


def check_destination(url: str | None, *, timeout: float = 8.0) -> dict | None:
    """ok | invalid (bad address, no such host, 404/410) | unverified (timeout,
    5xx, blocked): only a definite failure counts as invalid."""
    if not url:
        return None
    from urllib.parse import urlparse

    import requests

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return {"status": "invalid", "detail": "not a web address"}
    try:
        response = requests.head(url, allow_redirects=True, timeout=timeout)
        if response.status_code in (405, 403, 400):  # some sites refuse HEAD
            response = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
    except requests.exceptions.ConnectionError as exc:
        text = str(exc).lower()
        if any(s in text for s in ("name or service not known", "nodename nor servname", "getaddrinfo failed",
                                   "failed to resolve", "no address associated")):
            return {"status": "invalid", "detail": f"{parsed.hostname} doesn't exist"}
        return {"status": "unverified", "detail": "couldn't connect"}
    except requests.exceptions.RequestException:
        return {"status": "unverified", "detail": "the site didn't answer in time"}
    if response.status_code in (404, 410):
        return {"status": "invalid", "detail": f"the page returns {response.status_code} (not found)"}
    if response.status_code >= 500:
        return {"status": "unverified", "detail": f"the site returned {response.status_code}"}
    return {"status": "ok", "detail": f"answers {response.status_code}"}


def campaign_history(org_id: str | None, domain_category: str, *, exclude: str | None = None) -> dict | None:
    """Measured past campaigns of this organisation in this category."""
    if not org_id:
        return None
    try:
        from src.db.supabase_client import get_client

        client = get_client()
        rows = (client.table("campaigns").select("id").eq("org_id", org_id).eq("domain_category", domain_category)
                .execute().data or [])
        ids = [r["id"] for r in rows if r["id"] != exclude]
        if not ids:
            return {"campaigns": 0, "mean_reward": None}
        metrics = client.table("metrics").select("campaign_id,reward").in_("campaign_id", ids).execute().data or []
        per: dict[str, list[float]] = {}
        for m in metrics:
            per.setdefault(m["campaign_id"], []).append(float(m["reward"]))
        means = [sum(v) / len(v) for v in per.values()]
        return {"campaigns": len(means), "mean_reward": sum(means) / len(means) if means else None}
    except Exception as exc:
        logger.warning("campaign history unavailable: %s", exc)
        return None


def inputs_from(
    idea: str, feasibility, personas, *, domain_category: str, target_language: str = "en", org_id: str | None = None,
    campaign_id: str | None = None, cta_url: str | None = None, banned_terms: list[str] | tuple = (),
) -> DecisionInputs:
    from src.constants import active_channels

    signals = getattr(feasibility, "signals", None) or {}
    community = []
    for key in ("bluesky", "mastodon", "reddit"):
        if key in signals:
            community.append({**signals[key], "source": f"{key.capitalize()} search"})
    return DecisionInputs(
        idea=idea, domain_category=domain_category, target_language=target_language,
        feasibility_score=getattr(feasibility, "score", None),
        keyword=str((signals.get("trend") or {}).get("keyword") or (signals.get("news") or {}).get("keyword") or ""),
        trend=signals.get("trend"), news=signals.get("news"), community=community,
        personas=[{"channel_fit": getattr(p, "channel_fit", None) or (p.get("channel_fit") if isinstance(p, dict) else "")}
                  for p in personas or []],
        active_channels=active_channels(), history=campaign_history(org_id, domain_category, exclude=campaign_id),
        cta_url=cta_url, destination=check_destination(cta_url), banned_terms=list(banned_terms),
        competitor_activity=_competitor_activity(org_id, idea),
    )


def _competitor_activity(org_id: str | None, idea: str) -> list[dict]:
    from src.capabilities.competitors import recent_activity

    return recent_activity(org_id, idea)


def inputs_from_snapshot(snapshot: dict, **fresh) -> DecisionInputs:
    """Rebuild the inputs a stored decision was made from, optionally with
    fresh signals (e.g. trend=..., news=...) for a re-evaluation."""
    data = {**snapshot, **fresh}
    return DecisionInputs(
        idea=data.get("idea", ""), domain_category=data.get("domain_category", "other"),
        target_language=data.get("target_language", "en"), feasibility_score=data.get("feasibility_score"),
        keyword=data.get("keyword", ""), trend=data.get("trend"), news=data.get("news"),
        community=data.get("community") or [], personas=data.get("personas") or [],
        active_channels=data.get("active_channels") or ["bluesky", "email"], history=data.get("history"),
        cta_url=data.get("cta_url"), destination=data.get("destination"),
        competitor_activity=data.get("competitor_activity") or [],
    )


def reevaluate_waiting(campaign: dict, trend: dict | None, news: dict | None, *, now: datetime | None = None) -> Decision | None:
    """For a campaign at Gate 1 whose latest decision is WAIT: once its trigger
    fires (search interest reached the threshold), decide again with the
    fresh signals and store it as a re-evaluation. Returns the new decision,
    or None when there's nothing to do."""
    if campaign.get("status") != "awaiting_gate_1":
        return None
    from src.db.supabase_client import get_client

    rows = (get_client().table("campaign_decisions").select("decision,reevaluate,inputs,org_id,user_id")
            .eq("campaign_id", campaign["id"]).order("created_at", desc=True).limit(1).execute().data)
    if not rows or rows[0]["decision"] != "WAIT":
        return None
    latest, trigger = rows[0], rows[0].get("reevaluate") or {}
    if trigger.get("type") != "trend_threshold" or not trend or trend.get("error") or trend.get("rate_limited"):
        return None
    if float(trend.get("latest_interest") or 0) < float(trigger.get("threshold") or 0):
        return None
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat()
    inputs = inputs_from_snapshot(
        latest.get("inputs") or {}, trend={**trend, "fetched_at": stamp},
        **({"news": {**news, "fetched_at": stamp}} if news and not news.get("error") else {}),
    )
    decision = evaluate(inputs, now=now)
    save(decision, inputs, campaign_id=campaign["id"], user_id=latest.get("user_id"), org_id=latest.get("org_id"),
         trigger="reevaluation")
    return decision


# --- Persistence ---------------------------------------------------------------------


def save(decision: Decision, inputs: DecisionInputs, *, campaign_id: str, user_id: str | None, org_id: str | None,
         trigger: str = "initial") -> None:
    """Store the decision with its inputs snapshot (never raises)."""
    try:
        from src.db.supabase_client import get_client

        get_client().table("campaign_decisions").insert({
            "campaign_id": campaign_id, "user_id": user_id, "org_id": org_id, "trigger": trigger,
            "decision": decision.decision, "opportunity_score": decision.opportunity_score,
            "uncertainty": decision.uncertainty, "reason_codes": decision.reason_codes,
            "factors": [f.model_dump() for f in decision.factors], "hard_blocks": decision.hard_blocks,
            "review_flags": decision.review_flags, "constraints": decision.constraints,
            "reevaluate": decision.reevaluate, "baseline": decision.baseline,
            "policy_version": decision.policy_version, "inputs": inputs.snapshot(),
        }).execute()
    except Exception as exc:
        logger.warning("storing the decision for %s failed: %s", campaign_id, exc)


def record_outcome(campaign_id: str, summary: dict) -> None:
    """At the end of a campaign: write what actually happened onto its latest decision."""
    try:
        from src.db.supabase_client import get_client

        client = get_client()
        row = (client.table("campaign_decisions").select("id").eq("campaign_id", campaign_id)
               .order("created_at", desc=True).limit(1).execute().data)
        if not row:
            return
        trend = summary.get("reward_trend") or []
        client.table("campaign_decisions").update({"outcome": {
            "rounds": summary.get("total_rounds"),
            "best_reward": (summary.get("winning_round") or {}).get("reward"),
            "mean_reward": round(sum(r["reward"] for r in trend) / len(trend), 4) if trend else None,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }}).eq("id", row[0]["id"]).execute()
    except Exception as exc:
        logger.warning("recording the outcome for %s failed: %s", campaign_id, exc)
