"""Competitor intelligence: what are competitors doing, and should we respond?

Search interest says a topic is hot; it doesn't say a competitor just cut its
price or launched something. This module watches the competitors an
organisation lists, through public sources a person approved for each:

  webpage  pages they name (pricing, home): fetched at most daily, only if the
           site's robots.txt allows it (RFC 9309), with an identified user
           agent, a size cap and no private-network addresses
  rss      their blog / press feed
  news     news coverage (NewsAPI), by the names they go by
  bluesky  their public posts (the AT Protocol's public API)

What changed becomes a timestamped event with its source: OFFER_CHANGE,
MESSAGING_SHIFT, PRODUCT_LAUNCH or CONTENT_THEME. These are *observed*: the
quote, the before and after, the link. Duplicate and syndicated reports of one
story are folded into one event (so ten outlets running the same wire story
are one signal, with ten outlets listed).

Each new event gets an insight (policy `competitor-v1`, deterministic):
RESPOND, MONITOR, DIFFERENTIATE or NO_ACTION, with all four options and why,
the event's confidence and its relevance to live campaigns. The *inferred*
intent (why they might have done it) comes from an LLM as labelled
hypotheses, with alternatives; it never decides the recommendation.

When the competitor's market has a search keyword, the insight also stores a
measurable forecast: the change in search interest over the next two weeks
(model `trend-v1`, backtested on held-out years: src/eval/competitor_benchmark.py),
checked against what actually happened once the horizon passes.

A source that fails or goes quiet is marked unavailable or stale, never
papered over. Nothing here copies competitor messaging into our ads: the
decision engine only gets a review flag.
"""
import hashlib
import ipaddress
import json
import logging
import re
import socket
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

logger = logging.getLogger("capabilities.competitors")

POLICY_VERSION = "competitor-v1"
USER_AGENT = "CampaignIQ-CompetitorWatch/1.0 (+https://github.com/campaigniq; respects robots.txt)"
FETCH_EVERY_HOURS = {"webpage": 24, "rss": 6, "news": 12, "bluesky": 6}
STALE_AFTER_HOURS = 72          # a source with nothing fetched successfully for this long is stale
MAX_BYTES = 1_500_000
TIMEOUT = 15
EVENT_KINDS = ("OFFER_CHANGE", "MESSAGING_SHIFT", "PRODUCT_LAUNCH", "CONTENT_THEME")
ACTIONS = ("RESPOND", "MONITOR", "DIFFERENTIATE", "NO_ACTION")
STORY_SIMILARITY = 0.5          # word overlap above which two headlines are one story
STORY_WINDOW_DAYS = 7
MAX_FORECASTS_PER_SWEEP = 4     # Google Trends rate-limits hard

_STOP = set("""a an and are as at be been but by for from has have he her his i in into is it its new of on or our
that the their them they this to was we were will with you your after over than more just about up out off how why what
says said""".split())


# --- Safe fetching ---------------------------------------------------------------------------

class FetchError(Exception):
    pass


def public_host(host: str) -> bool:
    """Only hosts whose every address is public: no loopback, private, link-local
    or metadata addresses (the worker must never be pointed inside a network)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def _get(url: str, *, accept: str = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.5"):
    """GET with redirects checked hop by hop, a size cap and our user agent."""
    import requests

    for _ in range(4):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or not public_host(parts.hostname):
            raise FetchError(f"not a public web address: {url[:120]}")
        response = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept": accept}, timeout=TIMEOUT,
                                allow_redirects=False, stream=True)
        if response.is_redirect and response.headers.get("location"):
            url = urljoin(url, response.headers["location"])
            continue
        body = b""
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                break
        return response.status_code, body[:MAX_BYTES], response.headers.get("content-type", "")
    raise FetchError("too many redirects")


_robots_cache: dict[str, RobotFileParser | None] = {}


def robots_allows(url: str, *, fetch=None) -> bool:
    """RFC 9309: a 4xx robots.txt (none published) allows everything; a 5xx or an
    unreachable one means everything is disallowed until it can be read."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _robots_cache:
        try:
            status, body, _ = (fetch or _get)(f"{origin}/robots.txt", accept="text/plain")
        except Exception:
            _robots_cache[origin] = None
        else:
            parser = RobotFileParser()
            if 400 <= status < 500:
                parser.parse([])
            elif status >= 500:
                parser = None
            else:
                parser.parse(body.decode("utf-8", "replace").splitlines())
            _robots_cache[origin] = parser
    parser = _robots_cache[origin]
    return bool(parser and parser.can_fetch(USER_AGENT, url))


# --- Extracting what a page says ---------------------------------------------------------------

class _PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.h1, self.h2, self.text = "", {}, [], [], []
        self._tag, self._skip = None, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip += 1
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key in ("description", "og:title", "og:description") and a.get("content"):
                self.meta[key] = a["content"]
        if tag in ("title", "h1", "h2"):
            self._tag = tag
            if tag != "title":
                getattr(self, tag).append("")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template") and self._skip:
            self._skip -= 1
        if tag == self._tag:
            self._tag = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._tag == "title":
            self.title += data
        elif self._tag in ("h1", "h2"):
            getattr(self, self._tag)[-1] += data
        if data.strip():
            self.text.append(data)


_PRICE = re.compile(r"(?:[$€£₹]\s?\d[\d,]*(?:\.\d{1,2})?|\d[\d,]*(?:\.\d{1,2})?\s?(?:USD|EUR|GBP|INR|usd|eur))(?:\s?/\s?(?:mo|month|yr|year|week))?")
_OFFER = re.compile(
    r"\b(\d{1,2}\s?% off|save \$?\d+%?|free (?:trial|shipping|delivery|month|for \d+ \w+)|first (?:month|order|box) free|"
    r"buy one,? get one|bogo|promo code|coupon|limited[- ]time|sale ends|black friday|cyber monday|half price|\d+ ?% discount)\b",
    re.I,
)
_LAUNCH = re.compile(r"\b(introducing|now available|just launched|launch(?:es|ed|ing)?|unveil(?:s|ed)?|meet the new|debut(?:s|ed)?|"
                     r"rolls? out|new (?:[\w-]+ ){0,2}(?:product|app|feature|flavou?r|model|line|collection|range|service|plan|"
                     r"subscription|menu|store|trainer|shoe|device|kit|box))\b", re.I)
_OFFER_NEWS = re.compile(r"\b(price cuts?|(?:cuts?|slash(?:es)?|lowers?|drops?) (?:[\w-]+ ){0,3}prices?|discount(?:s|ed)?|\d{1,2}\s?% off|free trial|promotion|"
                         r"price (?:hike|increase|rise)s?|raises? prices?|sale|deal|cheaper)\b", re.I)
_MESSAGING_NEWS = re.compile(r"\b(rebrand(?:s|ed|ing)?|new (?:slogan|tagline|logo|identity|campaign)|ad campaign|reposition(?:s|ed|ing)?|"
                             r"marketing (?:push|campaign)|brand refresh)\b", re.I)


def _clean(text: str, limit: int = 200) -> str:
    return " ".join(text.split())[:limit]


def _sentences_with(pattern: re.Pattern, text: str, limit: int = 10) -> list[str]:
    found = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if pattern.search(sentence):
            s = _clean(sentence, 160)
            if s and s not in found:
                found.append(s)
        if len(found) >= limit:
            break
    return found


def extract_page(html: str) -> dict:
    """The parts of a page that carry positioning: short excerpts, not the page."""
    p = _PageParser()
    try:
        p.feed(html)
    except Exception:  # broken markup: keep what was parsed
        pass
    text = "\n".join(p.text)
    headline = _clean(p.meta.get("og:title") or (p.h1[0] if p.h1 else "") or p.title, 160)
    return {
        "title": _clean(p.title, 160),
        "headline": headline,
        "description": _clean(p.meta.get("description") or p.meta.get("og:description") or "", 300),
        "headings": [h for h in (_clean(x, 140) for x in p.h1 + p.h2) if h][:12],
        "prices": sorted(set(_clean(m.group(0), 30) for m in _PRICE.finditer(text)))[:20],
        "offers": _sentences_with(_OFFER, text),
    }


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


@dataclass
class Observed:
    """One observed change, before it's stored."""
    kind: str
    summary: str
    observed: dict
    url: str | None
    outlet: str | None
    published_at: str | None
    story_key: str
    confidence: float
    title: str = ""  # for story matching (headline-like text)


def diff_page(before: dict | None, after: dict, *, url: str, outlet: str) -> list[Observed]:
    """Events from what changed between two snapshots of a page. The first
    snapshot is only a baseline: nothing can be said to have changed yet."""
    if not before:
        return []
    events: list[Observed] = []
    added = [o for o in after.get("offers", []) if o not in before.get("offers", [])]
    ended = [o for o in before.get("offers", []) if o not in after.get("offers", [])]
    for offer in added[:3]:
        events.append(Observed("OFFER_CHANGE", f"New offer on {outlet}: “{offer}”", {"change": "added", "after": offer},
                               url, outlet, None, _key("page", url, "offer+", offer), 0.9, offer))
    for offer in ended[:3]:
        events.append(Observed("OFFER_CHANGE", f"Offer no longer shown on {outlet}: “{offer}”", {"change": "removed", "before": offer},
                               url, outlet, None, _key("page", url, "offer-", offer), 0.9, offer))
    if set(after.get("prices", [])) != set(before.get("prices", [])) and (after.get("prices") or before.get("prices")):
        events.append(Observed("OFFER_CHANGE", f"Prices changed on {outlet}",
                               {"change": "prices", "before": before.get("prices", []), "after": after.get("prices", [])},
                               url, outlet, None, _key("page", url, "prices", json.dumps(after.get("prices", []))), 0.9))
    for part in ("headline", "description"):
        old, new = before.get(part) or "", after.get(part) or ""
        if new and old and new != old:
            events.append(Observed("MESSAGING_SHIFT", f"{outlet} changed its {part}: “{new}”", {"field": part, "before": old, "after": new},
                                   url, outlet, None, _key("page", url, part, new), 0.9, new))
    new_headings = [h for h in after.get("headings", []) if h not in before.get("headings", []) and _LAUNCH.search(h)]
    for h in new_headings[:2]:
        events.append(Observed("PRODUCT_LAUNCH", f"New on {outlet}: “{h}”", {"quote": h}, url, outlet, None, _key("page", url, "launch", h), 0.9, h))
    return events


def classify_item(text: str) -> str | None:
    """Which move a headline or post reports, or None (it isn't a move)."""
    if _LAUNCH.search(text):
        return "PRODUCT_LAUNCH"
    if _OFFER_NEWS.search(text) or _OFFER.search(text):
        return "OFFER_CHANGE"
    if _MESSAGING_NEWS.search(text):
        return "MESSAGING_SHIFT"
    return None


def normalise_title(title: str) -> str:
    """Drop the " - Outlet" / " | Outlet" suffix and punctuation, lower-case."""
    t = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,60}$", "", title.strip())
    return " ".join(re.findall(r"[\w']+", t.lower()))


def _words(title: str) -> set[str]:
    return {w for w in normalise_title(title).split() if w not in _STOP and len(w) > 1}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def assign_stories(items: list[Observed], known: list[dict]) -> list[Observed]:
    """Give reports of the same story the same story key: an earlier event's
    (from `known`: {story_key, kind, title}) or the first report in this batch.
    Syndicated copies and rewrites of one story then count once."""
    pool = [{"story_key": k["story_key"], "kind": k["kind"], "title": k.get("title") or ""} for k in known]
    for item in items:
        if not item.title:
            continue
        match = max((p for p in pool if p["kind"] == item.kind), key=lambda p: similarity(item.title, p["title"]), default=None)
        if match and similarity(item.title, match["title"]) >= STORY_SIMILARITY:
            item.story_key = match["story_key"]
        else:
            pool.append({"story_key": item.story_key, "kind": item.kind, "title": item.title})
    return items


def mentions(text: str, names: list[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"(?<!\w){re.escape(n.lower())}(?!\w)", low) for n in names if n)


def news_events(articles: list[dict], names: list[str]) -> list[Observed]:
    events = []
    for a in articles:
        text = f"{a.get('title', '')}. {a.get('description') or ''}"
        if not mentions(text, names):
            continue  # the query matched loosely: not about them
        kind = classify_item(text)
        if not kind:
            continue
        title = a["title"]
        events.append(Observed(kind, _clean(title, 240), {"headline": _clean(title, 300), "snippet": _clean(a.get("description") or "", 300)},
                               a.get("url"), a.get("outlet"), a.get("published_at"), _key("news", normalise_title(title)), 0.6, title))
    return events


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 or Atom items: {title, url, published_at, text}."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for it in root.iter("item"):
        items.append({"title": (it.findtext("title") or "").strip(), "url": (it.findtext("link") or "").strip(),
                      "published_at": _rfc822(it.findtext("pubDate")), "text": _strip_tags(it.findtext("description") or "")})
    for it in root.iter("{http://www.w3.org/2005/Atom}entry"):
        link = it.find("atom:link", ns)
        items.append({"title": (it.findtext("atom:title", default="", namespaces=ns)).strip(),
                      "url": link.get("href") if link is not None else "",
                      "published_at": it.findtext("atom:published", default=None, namespaces=ns) or it.findtext("atom:updated", default=None, namespaces=ns),
                      "text": _strip_tags(it.findtext("atom:summary", default="", namespaces=ns))})
    return [i for i in items if i["title"]][:50]


def _strip_tags(html: str) -> str:
    return _clean(re.sub(r"<[^>]+>", " ", html), 400)


def _rfc822(value: str | None) -> str | None:
    if not value:
        return None
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def own_channel_events(items: list[dict], *, outlet: str) -> list[Observed]:
    """Their own posts announcing a move (feed items, Bluesky posts)."""
    events = []
    for it in items:
        text = f"{it['title']}. {it.get('text') or ''}"
        kind = classify_item(text)
        if kind:
            events.append(Observed(kind, _clean(it["title"], 240), {"quote": _clean(it["title"], 300), "snippet": _clean(it.get("text") or "", 300)},
                                   it.get("url"), outlet, it.get("published_at"), _key("own", outlet, normalise_title(it["title"])), 0.85, it["title"]))
    return events


def theme_events(items: list[dict], *, names: list[str], outlet: str, now: datetime,
                 recent_days: int = 14, history_days: int = 56) -> list[Observed]:
    """CONTENT_THEME: a term they now post about much more than before (at least
    3 recent posts, and 3x its earlier share or new)."""
    recent, earlier = [], []
    for it in items:
        t = _parse(it.get("published_at"))
        if not t:
            continue
        age = (now - t).days
        (recent if age <= recent_days else earlier if age <= history_days else []).append(it)
    if len(recent) < 3:
        return []
    banned = {w.lower() for n in names for w in n.split()}

    def terms(rows):
        counts: dict[str, int] = {}
        for r in rows:
            words = [w for w in re.findall(r"[a-z][a-z'-]{2,}", f"{r['title']} {r.get('text') or ''}".lower())
                     if w not in _STOP and w not in banned]
            for term in set(words + [f"{a} {b}" for a, b in zip(words, words[1:])]):
                counts[term] = counts.get(term, 0) + 1
        return counts

    now_counts, then_counts = terms(recent), terms(earlier)
    events = []
    # Most mentioned first; on a tie the longer phrase ("oat milk" over "milk").
    for term, n in sorted(now_counts.items(), key=lambda kv: (-kv[1], -len(kv[0].split()), kv[0])):
        share_now = n / len(recent)
        share_then = then_counts.get(term, 0) / len(earlier) if earlier else 0.0
        if n >= 3 and share_now >= 0.3 and (share_then == 0 or share_now >= 3 * share_then):
            examples = [r for r in recent if term in f"{r['title']} {r.get('text') or ''}".lower()][:3]
            events.append(Observed("CONTENT_THEME", f"{outlet} is posting about “{term}” ({n} of {len(recent)} recent posts)",
                                   {"term": term, "recent": n, "recent_total": len(recent), "earlier_share": round(share_then, 2),
                                    "examples": [{"title": _clean(e["title"], 160), "url": e.get("url")} for e in examples]},
                                   examples[0].get("url") if examples else None, outlet, examples[0].get("published_at") if examples else None,
                                   _key("theme", outlet, term, now.strftime("%G-%V")), 0.7, f"theme {term}"))
        if len(events) >= 2:
            break
    return events


def _parse(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# --- The recommendation (policy competitor-v1) ---------------------------------------------------

_DISCOUNT = re.compile(r"(\d{1,2})\s?%")


def discount_of(event: dict) -> int | None:
    text = json.dumps(event.get("observed") or {}) + " " + (event.get("summary") or "")
    found = [int(m.group(1)) for m in _DISCOUNT.finditer(text)]
    if found:
        return max(found)
    return 100 if re.search(r"\bfree\b", text, re.I) else None


def relevance(competitor: dict, campaigns: list[dict]) -> dict:
    """Live campaigns this competitor could affect: same market keyword or name in the idea."""
    market = {w for w in re.findall(r"\w+", (competitor.get("category_keyword") or "").lower()) if w not in _STOP}
    hits = []
    for c in campaigns:
        idea = (c.get("idea") or "").lower()
        words = set(re.findall(r"\w+", idea))
        if (market and len(market & words) >= max(1, len(market) // 2)) or mentions(idea, [competitor.get("name", "")]):
            hits.append({"id": c["id"], "idea": (c.get("idea") or "")[:120]})
    return {"live_campaigns": hits[:5], "relevant": bool(hits)}


def history_context(event: dict, past: list[dict]) -> dict:
    """How this compares with their earlier moves of the same kind (last 90 days)."""
    same = [p for p in past if p["kind"] == event["kind"] and p.get("id") != event.get("id")]
    out = {"same_kind_90d": len(same)}
    if same:
        last = max((_parse(p.get("observed_at")) for p in same if p.get("observed_at")), default=None)
        out["days_since_last"] = (datetime.now(timezone.utc) - last).days if last else None
    if event["kind"] == "OFFER_CHANGE":
        earlier = [d for d in (discount_of(p) for p in same) if d is not None and d < 100]
        now = discount_of(event)
        if earlier and now is not None and now < 100:
            out["deeper_than_before"] = now > max(earlier)
            out["previous_max_discount"] = max(earlier)
    return out


def recommend(event: dict, rel: dict, hist: dict) -> tuple[str, list[dict], float]:
    """(recommendation, all four options with reasons, confidence). Deterministic."""
    kind, conf = event["kind"], float(event.get("confidence") or 0.5)
    single_report = event.get("reports", 1) <= 1 and (event.get("source_kind") == "news")
    relevant = rel.get("relevant", False)
    change = (event.get("observed") or {}).get("change")
    pct = discount_of(event) if kind == "OFFER_CHANGE" else None
    reasons: dict[str, list[str]] = {a: [] for a in ACTIONS}

    if conf < 0.5 or (single_report and kind != "CONTENT_THEME"):
        pick = "MONITOR"
        reasons["MONITOR"].append("UNCONFIRMED")
    elif not relevant:
        pick = "NO_ACTION" if kind == "CONTENT_THEME" else "MONITOR"
        reasons[pick].append("NO_LIVE_CAMPAIGN_AFFECTED")
    elif kind == "OFFER_CHANGE":
        if change == "removed":
            pick = "NO_ACTION"
            reasons["NO_ACTION"].append("OFFER_ENDED")
        elif pct is not None and pct >= 30 and hist.get("deeper_than_before", True):
            pick = "RESPOND"
            reasons["RESPOND"].append("DEEP_OFFER_ON_YOUR_MARKET")
        else:
            pick = "DIFFERENTIATE"
            reasons["DIFFERENTIATE"].append("AVOID_PRICE_WAR")
    elif kind == "PRODUCT_LAUNCH":
        pick = "RESPOND"
        reasons["RESPOND"].append("BUYERS_WILL_COMPARE")
    elif kind == "MESSAGING_SHIFT":
        pick = "DIFFERENTIATE"
        reasons["DIFFERENTIATE"].append("POSITIONING_MOVED")
    else:
        pick = "MONITOR"
        reasons["MONITOR"].append("THEME_ONLY")

    # The other options, each with why it wasn't picked: NO_ACTION is always on the table.
    defaults = {
        "RESPOND": "RESPOND_COSTS", "MONITOR": "MONITOR_WAITS", "DIFFERENTIATE": "DIFFERENTIATE_NEEDS_ANGLE",
        "NO_ACTION": "NO_ACTION_RISK" if relevant else "NO_ACTION_FINE",
    }
    options = [{"action": a, "recommended": a == pick, "reasons": reasons[a] or [defaults[a]]} for a in ACTIONS]
    confidence = round(min(0.95, conf * (1.0 if relevant else 0.8)), 2)
    return pick, options, confidence


def explain(event: dict, competitor: dict, *, user_id: str | None = None, language: str = "en") -> list[dict]:
    """Inferred intent: hypotheses about why, each with what would confirm or
    refute it. From the LLM when it answers sensibly, else generic ones. Always
    labelled as inference; never used to pick the recommendation."""
    try:
        from src.languages import language_name
        from src.llm_json import generate_json
        from src.prompts import PROMPTS
        from src.providers.registry import get_llm
        from src.security.prompt_guard import fence

        evidence = json.dumps({"kind": event["kind"], "summary": event["summary"], "observed": event.get("observed"),
                               "source": event.get("outlet"), "published_at": event.get("published_at")}, ensure_ascii=False)
        prompt, system = PROMPTS["competitor.explain"].render(
            competitor=fence(competitor.get("name", ""), "competitor"), evidence=fence(evidence, "evidence"),
            language=language_name(language),
        )
        parsed = generate_json(get_llm(user_id), prompt, system=system)
        rows = parsed.get("hypotheses", []) if isinstance(parsed, dict) else []
        out = []
        for r in rows[:4]:
            if not isinstance(r, dict):
                continue
            h = _clean(str(r.get("hypothesis", "")), 200)
            if h:
                out.append({"hypothesis": h, "would_confirm": _clean(str(r.get("would_confirm", "")), 200),
                            "would_refute": _clean(str(r.get("would_refute", "")), 200), "inferred": True, "source": "llm"})
        if len(out) >= 2:
            return out
    except Exception as exc:
        logger.warning("explanations for event %s unavailable: %s", event.get("id"), exc)
    return [{"hypothesis_code": code, "inferred": True, "source": "template"} for code in _GENERIC[event["kind"]]]


_GENERIC = {
    "OFFER_CHANGE": ["SEASONAL_PROMOTION", "DEMAND_SOFTENING", "ACQUISITION_PUSH"],
    "MESSAGING_SHIFT": ["NEW_AUDIENCE", "RESPONDING_TO_COMPETITION", "BRAND_REFRESH"],
    "PRODUCT_LAUNCH": ["CATEGORY_EXPANSION", "RESPONDING_TO_COMPETITION", "PLANNED_ROADMAP"],
    "CONTENT_THEME": ["CONTENT_CALENDAR", "TESTING_A_MESSAGE", "RESPONDING_TO_NEWS"],
}


# --- Forecasting (model trend-v1) ---------------------------------------------------------------

FORECAST_MODEL = "trend-v1"
HORIZON_WEEKS = 2
SEASONAL_WEIGHT, LAST_WEEK_WEIGHT = 0.25, 0.5   # fitted on 2021-2024 (src/eval/competitor_benchmark.py)
INTERVAL_INFLATION = 1.25                        # widens the in-sample 80% band to hold out of sample
RESIDUAL_WEEKS = 26
OPPORTUNITY_RISE = 0.10                          # a "rise" worth acting on: +10% search interest


def forecast_change(values: list[float], t: int) -> tuple[float, float] | None:
    """Predicted relative change of the mean of weeks t..t+1 over the mean of
    weeks t-4..t-1, and that base. Needs a year and a month of history."""
    if t < 57 or t > len(values):
        return None
    base = sum(values[t - 4:t]) / 4
    if base < 5:  # too close to Google's floor for a relative change to mean anything
        return None
    ly_next, ly_base = sum(values[t - 52:t - 50]) / 2, sum(values[t - 56:t - 52]) / 4
    seasonal = ly_next / ly_base - 1 if ly_base else 0.0
    last = values[t - 1] / base - 1
    return SEASONAL_WEIGHT * seasonal + LAST_WEEK_WEIGHT * last, base


def forecast_interval(values: list[float], t: int, level: float = 0.8) -> tuple[float, float] | None:
    """The interval from this series' own recent forecast errors (the last half
    year of forecasts whose outcome is known), widened by the held-out factor."""
    residuals = []
    for u in range(t - RESIDUAL_WEEKS - HORIZON_WEEKS, t - HORIZON_WEEKS + 1):
        f = forecast_change(values, u)
        if not f:
            continue
        actual = sum(values[u:u + HORIZON_WEEKS]) / HORIZON_WEEKS / f[1] - 1
        residuals.append(actual - f[0])
    if len(residuals) < 10:
        return None
    residuals.sort()
    q = (1 - level) / 2
    return residuals[int(q * len(residuals))] * INTERVAL_INFLATION, residuals[min(len(residuals) - 1, int((1 - q) * len(residuals)))] * INTERVAL_INFLATION


def observed_change(values: list[float], t: int) -> float | None:
    if t + HORIZON_WEEKS > len(values):
        return None
    base = sum(values[t - 4:t]) / 4
    return sum(values[t:t + HORIZON_WEEKS]) / HORIZON_WEEKS / base - 1 if base else None


def weekly_series(keyword: str) -> tuple[list[str], list[float]]:
    """Five years of weekly interest. Complete weeks only (Google's current week is partial)."""
    from pytrends.request import TrendReq

    t = TrendReq(hl="en-US", tz=0, timeout=(5, 25))
    t.build_payload([keyword], timeframe="today 5-y")
    df = t.interest_over_time()
    if df.empty:
        return [], []
    if "isPartial" in df.columns:
        df = df[~df["isPartial"].astype(bool)]
    return [d.strftime("%Y-%m-%d") for d in df.index], [float(v) for v in df[keyword]]


def make_prediction(keyword: str, *, now: datetime, series=None) -> dict | None:
    weeks, values = series or weekly_series(keyword)
    t = len(values)
    f = forecast_change(values, t)
    band = forecast_interval(values, t) if f else None
    if not f or not band:
        return None
    origin = date.fromisoformat(weeks[-1])
    return {
        "keyword": keyword, "horizon_days": 7 * HORIZON_WEEKS, "origin_week": origin.isoformat(),
        "resolve_after": (datetime.combine(origin, datetime.min.time(), timezone.utc) + timedelta(days=7 * (HORIZON_WEEKS + 1) + 2)).isoformat(),
        "predicted_change": round(f[0], 4), "interval_low": round(f[0] + band[0], 4), "interval_high": round(f[0] + band[1], 4),
        "model_version": FORECAST_MODEL,
    }


def resolve_prediction(pred: dict, *, series=None) -> dict:
    """What happened: the change over the forecast's two weeks, from a fresh series."""
    weeks, values = series or weekly_series(pred["keyword"])
    origin = pred["origin_week"] if isinstance(pred["origin_week"], str) else pred["origin_week"].isoformat()
    if origin not in weeks:
        return {"status": "unresolvable"}
    t = weeks.index(origin) + 1
    change = observed_change(values, t)
    if change is None:
        return {"status": "pending"}
    low, high = float(pred["interval_low"]), float(pred["interval_high"])
    return {
        "status": "resolved", "observed_change": round(change, 4), "abs_error": round(abs(change - float(pred["predicted_change"])), 4),
        "inside_interval": low <= change <= high,
        "materialized": change >= OPPORTUNITY_RISE if float(pred["predicted_change"]) >= OPPORTUNITY_RISE else None,
    }


# --- Storage, the sweep ---------------------------------------------------------------------------

def _client():
    from src.db.supabase_client import get_client

    return get_client()


@dataclass
class SourceResult:
    status: str
    events: list[Observed] = field(default_factory=list)
    error: str | None = None


def fetch_source(source: dict, competitor: dict, *, now: datetime) -> SourceResult:
    """Fetch one approved source and turn what changed into observed events. Never raises."""
    kind, loc = source["kind"], source["locator"]
    names = [competitor["name"], *(competitor.get("keywords") or [])]
    try:
        if kind == "webpage":
            if not robots_allows(loc):
                return SourceResult("blocked_by_robots", error="robots.txt doesn't allow fetching this page")
            status, body, ctype = _get(loc)
            if status >= 400:
                return SourceResult("unavailable", error=f"the page returned {status}")
            extract = extract_page(body.decode("utf-8", "replace"))
            before = _latest_snapshot(source["id"])
            _store_snapshot(source["id"], body, extract)
            return SourceResult("ok", diff_page(before, extract, url=loc, outlet=urlsplit(loc).hostname or loc))
        if kind == "rss":
            if not robots_allows(loc):
                return SourceResult("blocked_by_robots", error="robots.txt doesn't allow fetching this feed")
            status, body, _ = _get(loc, accept="application/rss+xml,application/atom+xml,application/xml,text/xml")
            if status >= 400:
                return SourceResult("unavailable", error=f"the feed returned {status}")
            items = parse_feed(body.decode("utf-8", "replace"))
            if not items:
                return SourceResult("unavailable", error="no items in the feed")
            outlet = f"{competitor['name']} (feed)"
            _store_snapshot(source["id"], body, {"items": items[:50]})
            return SourceResult("ok", own_channel_events(_new_items(source["id"], items, now), outlet=outlet)
                                + theme_events(items, names=names, outlet=outlet, now=now))
        if kind == "news":
            from src.tools.news import search_articles

            query = " OR ".join(f'"{n}"' for n in dict.fromkeys(n for n in names if n))
            since = (now - timedelta(days=STORY_WINDOW_DAYS)).date().isoformat()
            return SourceResult("ok", news_events(search_articles(query, since=since), names))
        if kind == "bluesky":
            import requests

            r = requests.get("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                             params={"actor": loc, "limit": 50, "filter": "posts_no_replies"},
                             headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            if r.status_code >= 400:
                return SourceResult("unavailable", error=f"Bluesky returned {r.status_code}")
            items = []
            for row in r.json().get("feed", []):
                post = row.get("post") or {}
                text = (post.get("record") or {}).get("text") or ""
                rkey = (post.get("uri") or "").rsplit("/", 1)[-1]
                items.append({"title": _clean(text, 200), "text": "", "url": f"https://bsky.app/profile/{loc}/post/{rkey}",
                              "published_at": (post.get("record") or {}).get("createdAt")})
            items = [i for i in items if i["title"]]
            outlet = f"@{loc}"
            _store_snapshot(source["id"], json.dumps(items).encode(), {"items": items[:50]})
            return SourceResult("ok", own_channel_events(_new_items(source["id"], items, now), outlet=outlet)
                                + theme_events(items, names=names, outlet=outlet, now=now))
        return SourceResult("unavailable", error=f"unknown source kind {kind}")
    except Exception as exc:
        logger.warning("competitor source %s (%s) failed: %s", source.get("id"), kind, exc)
        return SourceResult("unavailable", error=f"{type(exc).__name__}: {str(exc)[:200]}")


def _latest_snapshot(source_id: str) -> dict | None:
    rows = (_client().table("competitor_snapshots").select("extract").eq("source_id", source_id)
            .order("fetched_at", desc=True).limit(1).execute().data or [])
    return rows[0]["extract"] if rows else None


def _store_snapshot(source_id: str, body: bytes, extract: dict) -> None:
    _client().table("competitor_snapshots").insert({
        "source_id": source_id, "content_hash": hashlib.sha256(body).hexdigest(), "extract": extract}).execute()


def _new_items(source_id: str, items: list[dict], now: datetime) -> list[dict]:
    """Feed items and posts from the last week: older ones were there before we looked."""
    cutoff = now - timedelta(days=STORY_WINDOW_DAYS)
    return [i for i in items if (_parse(i.get("published_at")) or now) >= cutoff]


def due(source: dict, now: datetime) -> bool:
    last = _parse(source.get("last_fetched_at"))
    return not last or now - last >= timedelta(hours=FETCH_EVERY_HOURS[source["kind"]])


def source_status(source: dict, result: SourceResult, now: datetime) -> dict:
    """The status to store. A failure after a long quiet spell is 'stale', so
    old data is never shown as current."""
    update = {"last_fetched_at": now.isoformat(), "last_error": result.error}
    if result.status == "ok":
        update.update(status="ok", last_ok_at=now.isoformat(), last_error=None)
    else:
        last_ok = _parse(source.get("last_ok_at"))
        update["status"] = "stale" if (result.status == "unavailable" and last_ok and now - last_ok > timedelta(hours=STALE_AFTER_HOURS)) else result.status
    return update


def scan_competitor(competitor: dict, *, now: datetime | None = None, force: bool = False, forecasts: list | None = None) -> dict:
    """Fetch the competitor's due, approved sources; store new events, their
    insights and forecasts. Returns a summary."""
    now = now or datetime.now(timezone.utc)
    client = _client()
    sources = (client.table("competitor_sources").select("*").eq("competitor_id", competitor["id"])
               .eq("approved", True).execute().data or [])
    known = client.table("competitor_events").select("id,story_key,kind,summary,observed,observed_at").eq(
        "competitor_id", competitor["id"]).gte("observed_at", (now - timedelta(days=90)).isoformat()).execute().data or []
    known_titles = [{"story_key": k["story_key"], "kind": k["kind"],
                     "title": (k.get("observed") or {}).get("headline") or (k.get("observed") or {}).get("quote") or k["summary"]}
                    for k in known if _parse(k.get("observed_at")) and now - _parse(k["observed_at"]) <= timedelta(days=STORY_WINDOW_DAYS)]
    new_events, statuses = [], {}
    for source in sources:
        if not force and not due(source, now):
            continue
        result = fetch_source(source, competitor, now=now)
        client.table("competitor_sources").update(source_status(source, result, now)).eq("id", source["id"]).execute()
        statuses[source["id"]] = result.status
        for ob in assign_stories(result.events, known_titles):
            row = client.rpc("record_competitor_event", {
                "p_competitor": competitor["id"], "p_source": source["id"], "p_kind": ob.kind, "p_summary": ob.summary,
                "p_observed": ob.observed, "p_url": ob.url, "p_outlet": ob.outlet, "p_published_at": ob.published_at,
                "p_story_key": ob.story_key, "p_confidence": ob.confidence,
            }).execute().data or []
            if row and row[0]["is_new"]:
                new_events.append({"id": row[0]["event_id"], "kind": ob.kind, "summary": ob.summary, "observed": ob.observed,
                                   "outlet": ob.outlet, "published_at": ob.published_at, "confidence": ob.confidence,
                                   "source_kind": source["kind"], "reports": 1, "observed_at": now.isoformat()})
                known_titles.append({"story_key": ob.story_key, "kind": ob.kind, "title": ob.title or ob.summary})
    if new_events:
        campaigns = (client.table("campaigns").select("id,idea,status").eq("org_id", competitor["org_id"])
                     .not_.in_("status", ["completed", "rejected", "blocked", "failed"]).execute().data or [])
        rel = relevance(competitor, campaigns)
        for ev in new_events:
            pick, options, confidence = recommend(ev, rel, history_context(ev, known))
            client.table("competitor_insights").upsert({
                "competitor_id": competitor["id"], "org_id": competitor["org_id"], "event_id": ev["id"], "recommendation": pick,
                "options": options, "explanations": explain(ev, competitor), "confidence": confidence,
                "relevance": {**rel, "history": history_context(ev, known)}, "policy_version": POLICY_VERSION,
            }, on_conflict="event_id").execute()
            if competitor.get("category_keyword") and ev["kind"] != "CONTENT_THEME" and (forecasts is None or len(forecasts) < MAX_FORECASTS_PER_SWEEP):
                _forecast(competitor, ev, now, forecasts)
    return {"competitor": competitor["id"], "sources": statuses, "new_events": len(new_events)}


_series_cache: dict[str, tuple[list[str], list[float]]] = {}


def _forecast(competitor: dict, event: dict, now: datetime, forecasts: list | None) -> None:
    keyword = competitor["category_keyword"]
    try:
        series = _series_cache.get(keyword) or weekly_series(keyword)
        _series_cache[keyword] = series
        pred = make_prediction(keyword, now=now, series=series)
        if forecasts is not None:
            forecasts.append(keyword)
        if not pred:
            return
        # One forecast per market and week: a second move that week shares it.
        same = (_client().table("competitor_predictions").select("id").eq("competitor_id", competitor["id"])
                .eq("keyword", keyword).eq("origin_week", pred["origin_week"]).limit(1).execute().data or [])
        if same:
            return
        _client().table("competitor_predictions").upsert({
            **pred, "competitor_id": competitor["id"], "org_id": competitor["org_id"], "event_id": event["id"],
        }, on_conflict="event_id").execute()
    except Exception as exc:
        logger.warning("forecast for %r failed: %s", keyword, exc)


def resolve_due(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    rows = (_client().table("competitor_predictions").select("*").eq("status", "pending")
            .lte("resolve_after", now.isoformat()).limit(20).execute().data or [])
    done = 0
    for pred in rows:
        try:
            series = _series_cache.get(pred["keyword"]) or weekly_series(pred["keyword"])
            _series_cache[pred["keyword"]] = series
            outcome = resolve_prediction(pred, series=series)
            if outcome["status"] == "pending":
                continue
            _client().table("competitor_predictions").update({**outcome, "resolved_at": now.isoformat()}).eq("id", pred["id"]).execute()
            done += 1
        except Exception as exc:
            logger.warning("resolving prediction %s failed: %s", pred.get("id"), exc)
    return done


def sweep(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    competitors = _client().table("competitors").select("*").is_("archived_at", "null").execute().data or []
    forecasts: list = []
    events = 0
    for c in competitors:
        try:
            events += scan_competitor(c, now=now, forecasts=forecasts)["new_events"]
        except Exception as exc:  # one competitor's failure never stops the rest
            logger.warning("competitor scan for %s failed: %s", c.get("id"), exc)
    return {"competitors": len(competitors), "new_events": events, "resolved": resolve_due(now)}


def recent_activity(org_id: str | None, idea: str, *, days: int = 14) -> list[dict]:
    """Recent moves by tracked competitors in this idea's market (decision engine review flags)."""
    if not org_id:
        return []
    try:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        competitors = _client().table("competitors").select("id,name,category_keyword").eq("org_id", org_id).is_("archived_at", "null").execute().data or []
        relevant = [c for c in competitors if relevance(c, [{"id": "-", "idea": idea}])["relevant"]]
        if not relevant:
            return []
        rows = (_client().table("competitor_events").select("competitor_id,kind,summary,url,published_at,observed_at,confidence")
                .in_("competitor_id", [c["id"] for c in relevant]).gte("observed_at", since)
                .in_("kind", ["OFFER_CHANGE", "PRODUCT_LAUNCH", "MESSAGING_SHIFT"]).order("observed_at", desc=True).limit(5).execute().data or [])
        names = {c["id"]: c["name"] for c in relevant}
        return [{**r, "competitor": names.get(r["competitor_id"])} for r in rows]
    except Exception as exc:
        logger.warning("competitor activity for the decision engine unavailable: %s", exc)
        return []


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    print("Competitor intelligence:", sweep())
