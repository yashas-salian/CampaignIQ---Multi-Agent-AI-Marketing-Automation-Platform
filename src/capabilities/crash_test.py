"""Campaign crash test: how could this ad fail, before real customers see it?

Runs before Gate 2 on the finished ad (post text, on-image headline and
button, and what the picture shows) and produces a risk report:

1. Rule checks (deterministic, reproducible, `RULES_VERSION`): the
   brand-safety guardrails plus checks grounded in real ad law and policy:
     * invented testimonials and reviews (FTC rule on fake reviews and
       testimonials, 16 CFR 465, in force Oct 2024: covers AI-made ones);
     * false urgency/scarcity and fake social proof (FTC staff report
       "Bringing Dark Patterns to Light", 2022);
     * asserting a viewer's personal attributes, e.g. "Are you in debt?"
       (Meta advertising standards);
     * numbers and claims the brand never stated (substantiation);
     * a broken call-to-action link.
   Only rule checks can rate a finding CRITICAL.
2. Simulated scenarios (`SCENARIO_SET`): one LLM call plays a versioned set
   of situations (a skeptic, a price-sensitive buyer, a competitor's discount,
   an ad-standards reviewer, a three-second scroll, a sensitivity read, the
   wrong audience, a non-native reader). Every finding must quote the exact ad
   text it's about (else it's anchored to the whole ad), and is capped at
   HIGH: agreement between simulated people shares one model's biases and is
   never treated as independent evidence.
3. Revise and re-test: when anything is HIGH or CRITICAL, one LLM call writes
   a revised version that fixes the findings without inventing anything; the
   same checks and scenarios run on it, and the report shows what was
   resolved, what remains and what's new. A person chooses at Gate 2: the
   simulator never approves its own output.

Results are labelled simulation-only throughout. Any failure of the simulated
part leaves the rule checks standing (they never need the network).
"""
import logging
import re
import unicodedata
from datetime import datetime, timezone

from pydantic import BaseModel

logger = logging.getLogger("capabilities.crash_test")

SCENARIO_SET = "marketing-risk-v1"
RULES_VERSION = "rules-v1"
SEVERITIES = ("low", "medium", "high", "critical")
SIMULATED_MAX = "high"
REVISE_AT = "high"
MAX_REVISION_GROWTH = 1.2  # a revision longer than this has usually invented facts to answer the findings
RETRY_SHORTER = (
    "\n\nYour previous attempt was longer than the original ad. Make it shorter: fix the problems by removing or "
    "softening words, never by adding facts the brand didn't give."
)

SCENARIOS: list[dict] = [
    {"id": "skeptic", "who": "a skeptical customer who has been burned by ads before",
     "looks_for": "claims they don't believe, missing proof, anything that feels too good to be true"},
    {"id": "price_sensitive", "who": "a price-sensitive buyer comparing options",
     "looks_for": "whether the value is clear, hidden costs, reasons to wait or buy cheaper"},
    {"id": "competitor_discount", "who": "someone who just saw a competitor offer 20% off a similar product",
     "looks_for": "whether this ad still gives a reason to choose it over the discounted alternative"},
    {"id": "standards_reviewer", "who": "an advertising-standards reviewer reading every claim",
     "looks_for": "unsupported, exaggerated or misleading claims; anything that implies more than is stated"},
    {"id": "three_second_scroll", "who": "someone who sees the ad for three seconds while scrolling",
     "looks_for": "what they think is being sold, and anything ambiguous or easy to misread"},
    {"id": "sensitivity", "who": "a viewer from a different culture or background, alert to stereotypes",
     "looks_for": "insensitive, exclusionary or stereotyping wording or imagery"},
    {"id": "wrong_audience", "who": "someone outside the target audience who sees the ad anyway",
     "looks_for": "confusion, irrelevance or annoyance that could hurt the brand"},
    {"id": "non_native", "who": "a non-native reader of the ad's language",
     "looks_for": "idioms, slang, jargon or wordplay that won't translate"},
]
SCENARIO_IDS = {s["id"] for s in SCENARIOS}
RULE_TYPES = (
    "POLICY_VIOLATION", "INVENTED_TESTIMONIAL", "FAKE_SOCIAL_PROOF", "FALSE_URGENCY", "PERSONAL_ATTRIBUTE",
    "UNVERIFIED_NUMBER", "UNSUPPORTED_CLAIM", "INVALID_DESTINATION", "UNVERIFIED_DESTINATION", "READABILITY",
)
SIMULATED_TYPES = (
    "TRUST_GAP", "PRICE_OBJECTION", "COMPETITOR_VULNERABLE", "MISLEADING", "AMBIGUOUS_MESSAGE", "INSENSITIVE",
    "AUDIENCE_MISMATCH", "HARD_TO_UNDERSTAND", "WEAK_CTA", "UNSUPPORTED_CLAIM",
)


class AdText(BaseModel):
    body: str = ""  # the post / email text
    headline: str = ""  # set on the image
    cta: str = ""  # the button on the image
    visual: str = ""  # what the picture shows (for the simulation)


class Finding(BaseModel):
    key: str  # stable identity, for before/after comparison
    source: str  # rule | simulation
    scenario: str | None = None
    type: str
    severity: str
    quote: str | None = None  # exact text from the ad; None = the ad as a whole
    field: str | None = None  # body | headline | cta
    problem: str
    fix: str = ""


class CrashReport(BaseModel):
    scenario_set: str = SCENARIO_SET
    rules_version: str = RULES_VERSION
    simulation_only: bool = True
    status: str = "COMPLETED"  # COMPLETED | RULES_ONLY (the simulation couldn't run)
    ad: AdText
    findings: list[Finding]
    risk: str  # clear | low | medium | high | critical
    counts: dict[str, int]
    revised: AdText | None = None
    revision_notes: list[str] = []
    revised_findings: list[Finding] = []
    revised_risk: str | None = None
    comparison: dict | None = None
    note: str = ""
    created_at: str


# --- Helpers ---------------------------------------------------------------------

_HYPHENS = re.compile("[‐-―−]")
_QUOTE_MARKS = set("\"'‘’“”")


def _unify(text: str) -> str:
    """NFKC, straight quotes, one kind of hyphen."""
    text = unicodedata.normalize("NFKC", text or "")
    text = _HYPHENS.sub("-", text)
    text = re.sub("[‘’]", "'", text)
    return re.sub("[“”]", '"', text)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _unify(text).lower()).strip()


def _rank(severity: str) -> int:
    return SEVERITIES.index(severity) if severity in SEVERITIES else 0


def risk_of(findings: list[Finding]) -> str:
    if not findings:
        return "clear"
    return max((f.severity for f in findings), key=_rank)


def _counts(findings: list[Finding]) -> dict[str, int]:
    return {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}


def locate(ad: AdText, quote: str | None) -> tuple[str | None, str | None]:
    """(the quoted words exactly as they appear in the ad, field), or (None, None)
    when they aren't in it. Case, quote marks, hyphen style and spacing don't matter."""
    if not quote:
        return None, None
    tokens = [t for t in re.findall(r"\w+|[^\w\s]", _unify(quote)) if t not in _QUOTE_MARKS]
    while tokens and tokens[-1] in ".!?,;:":
        tokens.pop()
    if sum(len(t) for t in tokens) < 3:
        return None, None
    pattern = r"[\s\"']*".join(re.escape(t) for t in tokens)
    for field in ("headline", "cta", "body"):
        text = _unify(getattr(ad, field))
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(0), field
    return None, None


def _finding(source: str, type_: str, severity: str, problem: str, fix: str, ad: AdText, quote: str | None = None,
             scenario: str | None = None) -> Finding:
    anchored, field = locate(ad, quote)
    key = f"{source}:{scenario or '-'}:{type_}:{_norm(anchored or '')[:60]}"
    return Finding(key=key, source=source, scenario=scenario, type=type_, severity=severity, quote=anchored,
                   field=field, problem=problem, fix=fix)


# --- 1. Rule checks ---------------------------------------------------------------------

# A capitalised name + "says" is matched case-sensitively ((?-i:...)): "she says" or "it says" don't count.
_TESTIMONIAL = [
    # ...but not pronouns or sources that start a sentence ("She says", "Research says").
    r"\b(?!(?:She|He|It|They|We|You|This|That|Everyone|Nobody|Someone|Science|Research|Data|Experience)\b)"
    r"(?-i:[A-Z][a-z]+) (says|said|swears|told us|raves|loves it)\b",
    r"\"[^\"]{8,}\"\s*-\s*(?-i:[A-Z][a-z]+)",
    r"\b(our|happy|real|satisfied) customers (say|love|rave|agree)\b",
    r"\b(rated|rating of) \d(\.\d)? ?(/ ?5|stars?|out of 5)\b",
    r"\b\d(\.\d)?[- ]stars?\b|★{3,}",
    r"\b(thousands|millions|hundreds) of (happy|satisfied|loyal) (customers|users|fans)\b",
]
_SOCIAL_PROOF = [
    r"\b(join )?\d[\d,]* (people|customers|users|shoppers|families|commuters|members) "
    r"(bought|joined|ordered|are (viewing|buying|watching|using)|signed up|switched|already)\b",
    r"\bjoin \d[\d,]*\+? ",
    r"\b(best[- ]?selling|bestseller|#1 (rated|choice|seller)|most popular|everyone(?:'s| is) (buying|talking|switching))\b",
    r"\b(trusted by|loved by|used by) (thousands|millions|\d[\d,]*)\b",
]
_URGENCY = [
    r"\blimited[- ]time\b", r"\bonly \d+ (\w+ ){0,3}(left|remaining)\b", r"\bonly \d+ (spots?|seats?|places?)\b",
    r"\blast chance\b",
    r"\bends? (today|tonight|soon|at midnight)\b", r"\bhurry\b", r"\bwhile (stocks?|supplies) last\b",
    r"\b(spots?|seats?|places?|stock) (are )?(filling|running|selling) (up|out|fast)\b", r"\btoday only\b",
    r"\bdon'?t miss out\b", r"\bselling fast\b", r"\b(act|order|buy) now before\b", r"\b(run|runs|running) out\b",
    r"\b(sold out|gone) soon\b", r"\bfew (left|remaining)\b", r"\bsale ends\b", r"\bbefore (the )?summer rush\b",
]
_PERSONAL = [
    r"\bare you (overweight|fat|obese|depressed|anxious|lonely|single|broke|in debt|bankrupt|diabetic|infertile|addicted|"
    r"struggling with|suffering from|battling|dealing with (debt|depression|anxiety|addiction|weight))\b",
    r"\b(your|you have) (debt|diagnosis|condition|disease|weight problem|bad credit|addiction|depression|anxiety)\b",
    r"\bwe know (you|that you)\b",
]
_NUMBER = re.compile(
    r"(?:[₹$€£¥]\s?\d[\d,.]*|\d[\d,.]*\s?(?:%|percent\b|x\b|times\b)|"
    r"\d[\d,.]*\s?(?:minutes?|mins?|hours?|days?|weeks?|seconds?|kg|lbs?)\b)",
    re.IGNORECASE,
)

_RULE_CHECKS = [
    (_TESTIMONIAL, "INVENTED_TESTIMONIAL", "critical",
     "Presents a customer quote, review or rating the brand hasn't provided: fake or AI-made testimonials are illegal "
     "(FTC rule on reviews and testimonials, 16 CFR 465).",
     "Remove it, or replace it with a real, documented customer quote."),
    (_SOCIAL_PROOF, "FAKE_SOCIAL_PROOF", "high",
     "Claims popularity or customer numbers the brand never stated: fake social proof is a deceptive dark pattern (FTC).",
     "Remove it unless you can show the figures."),
    (_URGENCY, "FALSE_URGENCY", "high",
     "Creates urgency or scarcity the brand never stated: false urgency is a deceptive dark pattern (FTC).",
     "Remove the deadline or scarcity, or state the real one the brand gave you."),
    (_PERSONAL, "PERSONAL_ATTRIBUTE", "high",
     "Implies it knows something personal about the viewer (health, finances, relationships): Meta's ad standards don't allow it.",
     "Talk about the product's benefit instead of the viewer's situation."),
]


def rule_checks(
    ad: AdText, *, idea: str, tagline: str = "", domain_category: str = "other", channels: list[str] | tuple = (),
    cta_url: str | None = None, destination: dict | None = None, banned_terms: list[str] | tuple = (), language: str = "en",
) -> list[Finding]:
    """Deterministic: the same ad and context always give the same findings.
    Words the brand itself wrote (idea, tagline) are never "invented"."""
    from src.capabilities.guardrails import check_creative

    findings: list[Finding] = []
    stated = _norm(f"{idea} {tagline}")

    guard = check_creative(ad.body, domain_category=domain_category, channels=list(channels), cta_url=cta_url,
                           banned_terms=list(banned_terms), language=language)
    for issue in guard.issues:
        if issue.severity == "block":
            findings.append(_finding("rule", "POLICY_VIOLATION", "critical", issue.message, issue.fix or "", ad))
        elif issue.category == "claims":
            m = re.search(r'"([^"]+)"', issue.message)
            quote = m.group(1) if m else None
            severity = "medium" if quote and _norm(quote) in stated else "high"
            findings.append(_finding("rule", "UNSUPPORTED_CLAIM", severity, issue.message, issue.fix or "", ad, quote))
        elif issue.category == "readability":
            findings.append(_finding("rule", "READABILITY", "low", issue.message, issue.fix or "", ad))
    for field in ("headline", "cta"):
        text = getattr(ad, field)
        if text:
            for issue in check_creative(text, domain_category=domain_category, banned_terms=list(banned_terms),
                                        language=language, cta_url=cta_url).blocked:
                findings.append(_finding("rule", "POLICY_VIOLATION", "critical", f"On-image {field}: {issue.message}",
                                         issue.fix or "", ad))

    whole = _unify(f"{ad.headline}\n{ad.body}\n{ad.cta}")
    for patterns, type_, severity, problem, fix in _RULE_CHECKS:
        for pattern in patterns:
            found = next((m for m in re.finditer(pattern, whole, re.IGNORECASE) if _norm(m.group(0)) not in stated), None)
            if found:
                findings.append(_finding("rule", type_, severity, problem, fix, ad, found.group(0)))
    for m in _NUMBER.finditer(whole):
        number = m.group(0).strip()
        if _norm(number) in stated or any(f.quote and _norm(number) in _norm(f.quote) for f in findings):
            continue
        findings.append(_finding("rule", "UNVERIFIED_NUMBER", "medium",
                                 f'"{number}" isn\'t in the brief: numbers and prices in ads need evidence.',
                                 "Remove it or use the figure the brand gave you.", ad, number))
    if destination and destination.get("status") == "invalid":
        findings.append(_finding("rule", "INVALID_DESTINATION", "critical",
                                 f"The call-to-action link doesn't work: {destination.get('detail', '')}.",
                                 "Fix the link before anything goes out.", ad))
    elif destination and destination.get("status") == "unverified":
        findings.append(_finding("rule", "UNVERIFIED_DESTINATION", "low",
                                 f"The link couldn't be checked: {destination.get('detail', '')}.", "Open it once to be sure.", ad))
    unique: dict[str, Finding] = {}  # the same phrase can match more than one pattern
    for f in findings:
        unique.setdefault(f.key, f)
    return list(unique.values())


# --- 2. Simulated scenarios ---------------------------------------------------------------


def _ad_block(ad: AdText) -> str:
    return f"Headline on the image: {ad.headline}\nButton: {ad.cta}\nPost text: {ad.body}\nThe picture: {ad.visual}"


def _persona_panel(personas: list | None) -> str:
    rows = []
    for p in personas or []:
        get = (lambda k: p.get(k, "")) if isinstance(p, dict) else (lambda k: getattr(p, k, ""))
        rows.append(f"- {get('name')}: {get('demographics')} | {get('psychographics')}")
    return "\n".join(rows) or "- (no personas: use typical buyers of this product)"


def simulate(ad: AdText, *, idea: str, personas: list | None = None, language: str = "en",
             user_id: str | None = None) -> list[Finding]:
    from src.languages import language_name
    from src.llm_json import generate_json
    from src.prompts import PROMPTS
    from src.providers.registry import get_llm
    from src.security.prompt_guard import fence

    scenarios = "\n".join(f"- {s['id']}: {s['who']}; looks for {s['looks_for']}" for s in SCENARIOS)
    prompt, system = PROMPTS["crashtest.simulate"].render(
        idea=fence(idea, "user_idea"), ad=fence(_ad_block(ad), "ad"), personas=fence(_persona_panel(personas), "personas"),
        scenarios=scenarios, types=", ".join(SIMULATED_TYPES), language=language_name(language),
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)
    rows = parsed.get("scenarios", []) if isinstance(parsed, dict) else parsed if isinstance(parsed, list) else []
    findings: list[Finding] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in SCENARIO_IDS:
            continue
        for raw in (row.get("findings") or [])[:3]:
            if not isinstance(raw, dict):
                continue
            type_ = str(raw.get("type", "")).upper()
            if type_ not in SIMULATED_TYPES:
                continue
            severity = str(raw.get("severity", "low")).lower()
            severity = severity if severity in SEVERITIES else "low"
            if _rank(severity) > _rank(SIMULATED_MAX):  # simulated people can't make anything critical
                severity = SIMULATED_MAX
            problem = " ".join(str(raw.get("problem", "")).split())[:300]
            if not problem:
                continue
            findings.append(_finding("simulation", type_, severity, problem, " ".join(str(raw.get("fix", "")).split())[:300],
                                     ad, str(raw.get("quote") or "") or None, scenario=row["id"]))
    unique: dict[str, Finding] = {}
    for f in findings:
        unique.setdefault(f.key, f)
    return list(unique.values())


# --- 3. Revise and compare ------------------------------------------------------------------


def revise(ad: AdText, findings: list[Finding], *, idea: str, tagline: str = "", language: str = "en",
           user_id: str | None = None) -> tuple[AdText, list[str]]:
    from src.languages import language_name
    from src.llm_json import generate_json
    from src.prompts import PROMPTS
    from src.providers.registry import get_llm
    from src.security.prompt_guard import fence

    worst = sorted(findings, key=lambda f: -_rank(f.severity))[:10]
    issues = "\n".join(
        f"- [{f.severity}] {f.type}{' on ' + repr(f.quote) if f.quote else ''}: {f.problem} Fix: {f.fix}" for f in worst
    )
    prompt, system = PROMPTS["crashtest.revise"].render(
        idea=fence(idea, "user_idea"), tagline=fence(tagline or "none", "tagline"), ad=fence(_ad_block(ad), "ad"),
        issues=fence(issues, "findings"), language=language_name(language),
    )
    llm = get_llm(user_id)
    parsed = generate_json(llm, prompt, system=system)
    # A revision that grew a lot has usually added "facts" (availability, timing,
    # fees) to answer the findings: ask once more for a shorter, fact-free fix.
    if len(str(parsed.get("copy") or "")) > MAX_REVISION_GROWTH * max(len(ad.body), 80):
        parsed = generate_json(llm, prompt + RETRY_SHORTER, system=system)

    def clean(key: str, fallback: str, limit: int) -> str:
        value = " ".join(str(parsed.get(key) or "").split())
        return value[:limit] if value else fallback

    revised = AdText(body=clean("copy", ad.body, 600), headline=clean("headline", ad.headline, 60),
                     cta=clean("cta", ad.cta, 24), visual=ad.visual)
    notes = [" ".join(str(n).split())[:200] for n in (parsed.get("changes") or [])[:6] if str(n).strip()]
    return revised, notes


def compare(before: list[Finding], after: list[Finding]) -> dict:
    """Which findings the revision resolved, which remain, which are new. Rule
    findings match on type + quoted text; simulated ones on scenario + type
    (a rewritten sentence won't quote the same words)."""
    def ident(f: Finding) -> str:
        return f"rule:{f.type}:{_norm(f.quote or '')}" if f.source == "rule" else f"sim:{f.scenario}:{f.type}"

    b = {ident(f): f for f in before}
    a = {ident(f): f for f in after}
    return {
        "resolved": [b[k].key for k in b if k not in a],
        "remaining": [a[k].key for k in a if k in b],
        "new": [a[k].key for k in a if k not in b],
    }


# --- The whole run ---------------------------------------------------------------------------


def _ordered(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (-_rank(f.severity), f.source != "rule"))


def run_crash_test(
    ad: AdText, *, idea: str, tagline: str = "", domain_category: str = "other", channels: list[str] | tuple = (),
    cta_url: str | None = None, destination: dict | None = None, banned_terms: list[str] | tuple = (),
    language: str = "en", personas: list | None = None, user_id: str | None = None, revise_at: str = REVISE_AT,
) -> CrashReport:
    context = dict(idea=idea, tagline=tagline, domain_category=domain_category, channels=channels, cta_url=cta_url,
                   destination=destination, banned_terms=banned_terms, language=language)
    findings = rule_checks(ad, **context)
    status, note = "COMPLETED", ""
    try:
        findings += simulate(ad, idea=idea, personas=personas, language=language, user_id=user_id)
    except Exception as exc:
        logger.warning("crash-test simulation failed, rule checks only: %s", exc)
        status, note = "RULES_ONLY", "The simulated scenarios couldn't run; the rule checks below still apply."
    findings = _ordered(findings)
    report = CrashReport(status=status, ad=ad, findings=findings, risk=risk_of(findings), counts=_counts(findings),
                         note=note, created_at=datetime.now(timezone.utc).isoformat())
    if not findings or _rank(report.risk) < _rank(revise_at):
        return report
    try:
        revised, notes = revise(ad, findings, idea=idea, tagline=tagline, language=language, user_id=user_id)
        after = rule_checks(revised, **context)
        if status == "COMPLETED":
            after += simulate(revised, idea=idea, personas=personas, language=language, user_id=user_id)
        after = _ordered(after)
        report.revised, report.revision_notes, report.revised_findings = revised, notes, after
        report.revised_risk = risk_of(after)
        report.comparison = compare(findings, after)
    except Exception as exc:
        logger.warning("crash-test revision failed: %s", exc)
        report.note = (report.note + " " if report.note else "") + "A revised version couldn't be written this time."
    return report


# --- Persistence ---------------------------------------------------------------------------


def save(report: CrashReport, *, campaign_id: str, round_number: int, org_id: str | None, user_id: str | None,
         trigger: str = "pipeline") -> str | None:
    """Store the report (never raises); returns its id."""
    try:
        from src.db.supabase_client import get_client

        row = get_client().table("crash_tests").insert({
            "campaign_id": campaign_id, "org_id": org_id, "user_id": user_id, "round_number": round_number,
            "trigger": trigger, "scenario_set": report.scenario_set, "rules_version": report.rules_version,
            "status": report.status, "risk": report.risk, "revised_risk": report.revised_risk,
            "report": report.model_dump(),
        }).execute()
        return (row.data or [{}])[0].get("id")
    except Exception as exc:
        logger.warning("storing the crash test for %s failed: %s", campaign_id, exc)
        return None


def run_for_round(campaign_id: str, round_number: int, *, user_id: str | None, ad: AdText,
                  idea: str | None = None, trigger: str = "pipeline") -> CrashReport:
    """Crash-test a campaign round's ad with the campaign's own context, and store it."""
    from src.capabilities.brand import brand_kit_for_campaign
    from src.capabilities.decision import check_destination
    from src.constants import active_channels
    from src.db.supabase_client import get_campaign, get_personas

    campaign = get_campaign(campaign_id)
    kit = brand_kit_for_campaign(campaign_id)
    report = run_crash_test(
        ad, idea=idea or campaign["idea"], tagline=campaign.get("product_tagline") or "",
        domain_category=campaign.get("domain_category") or "other", channels=active_channels(),
        cta_url=campaign.get("cta_url"), destination=check_destination(campaign.get("cta_url")),
        banned_terms=kit.forbidden_words if kit else (), language=campaign.get("target_language") or "en",
        personas=get_personas(campaign_id), user_id=user_id,
    )
    save(report, campaign_id=campaign_id, round_number=round_number, org_id=campaign.get("org_id"), user_id=user_id,
         trigger=trigger)
    return report
