"""Brand-safety and regulatory checks on generated ad copy.

Two severities:
  * block  -- must never be published as-is: links to anything but the
             campaign's own CTA domain (a classic prompt-injection payload),
             personal data (emails, phone numbers), banned terms, copy that
             won't fit a channel. generate_creative() rewrites the copy when
             it hits one, and distribution re-checks the final text (it may
             have been edited at a gate) and refuses to send.
  * review -- allowed, but a human must look at it at Gate 2: absolute or
             regulated claims ("cures", "guaranteed returns", "risk-free").
             Regulated categories also get a required disclaimer appended
             to emails.
Deterministic and free: no LLM call, so it can run on every creative.
"""
import os
import re
from urllib.parse import urlparse

from pydantic import BaseModel

BLUESKY_MAX_CHARS = 300  # Bluesky counts graphemes; code points are a safe upper bound

# Tiny built-in list (slurs/obscenities are better handled by the brand kit's
# per-organisation list); extend globally with BANNED_TERMS="a,b,c".
_DEFAULT_BANNED = ("fuck", "shit", "cunt", "nigger", "faggot", "retard")

DISCLAIMERS = {
    "healthcare": "This is not medical advice. Talk to a qualified healthcare professional before making health decisions.",
    "finance_fintech": "This is not financial advice. Investments can lose value; past performance does not guarantee future results.",
    "fitness_wellness": "Results vary. Consult a doctor before starting a new diet, supplement or exercise programme.",
}

# Claims regulators and ad platforms (FTC, ASA, Meta/Google ad policies)
# treat as high-risk. Applied to every domain; the regulated ones add more.
_ABSOLUTE_CLAIMS = [
    r"\bguarantee(d|s)?\b", r"\b100\s?% (safe|effective|natural|guaranteed)\b", r"\brisk[- ]free\b",
    r"\b(no|zero) side effects\b", r"\bmiracle\b", r"\b#1\b|\bnumber one\b", r"\bclinically proven\b",
]
_REGULATED_CLAIMS = {
    "healthcare": [r"\bcures?\b", r"\btreats?\b", r"\bheals?\b", r"\bprevents?\b.{0,20}\b(disease|cancer|diabetes|covid)\b",
                   r"\bfda[- ]approved\b", r"\bprescription\b", r"\bdiagnos(e|is)\b"],
    "finance_fintech": [r"\bguaranteed (returns?|profits?|income)\b", r"\b(double|triple) your (money|investment)\b",
                        r"\bget rich\b", r"\bno risk\b", r"\b\d{2,}\s?% (returns?|apy|interest|gains?)\b", r"\bpassive income\b"],
    "fitness_wellness": [r"\blose \d+\s?(kg|lbs?|pounds)\b", r"\bburns? fat\b", r"\bdetox\b", r"\bweight loss (pill|supplement)s?\b"],
}

_URL_RE = re.compile(r"\b((?:https?://)?(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|co|app|dev|xyz|info|biz|me|ly|gl|in|uk|us|shop|store|link|click)(?:/[^\s)]*)?)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{8,}\d)(?!\w)")


class Issue(BaseModel):
    code: str
    severity: str  # "block" | "review"
    message: str


class GuardrailResult(BaseModel):
    issues: list[Issue] = []
    disclaimer: str | None = None

    @property
    def blocked(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "block"]

    @property
    def needs_review(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "review"]

    @property
    def ok(self) -> bool:
        return not self.blocked


def _banned_terms(extra: tuple[str, ...] | list[str]) -> list[str]:
    env = [t.strip().lower() for t in os.environ.get("BANNED_TERMS", "").split(",") if t.strip()]
    return list(dict.fromkeys([*_DEFAULT_BANNED, *env, *(t.lower() for t in extra if t)]))


def _host(url: str) -> str:
    return (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower().removeprefix("www.")


def check_creative(
    copy_text: str,
    *,
    domain_category: str = "other",
    channels: list[str] | tuple[str, ...] = (),
    cta_url: str | None = None,
    banned_terms: tuple[str, ...] | list[str] = (),
) -> GuardrailResult:
    text = copy_text or ""
    lower = text.lower()
    issues: list[Issue] = []

    if not text.strip():
        issues.append(Issue(code="empty", severity="block", message="The copy is empty."))

    allowed_host = _host(cta_url) if cta_url else None
    for match in _URL_RE.findall(text):
        host = _host(match)
        if not allowed_host or not (host == allowed_host or host.endswith("." + allowed_host)):
            issues.append(Issue(code="foreign_link", severity="block",
                                message=f"Links to {host}, which isn't the campaign's own link. Remove it; the CTA link is added automatically."))
    if _EMAIL_RE.search(text):
        issues.append(Issue(code="personal_data", severity="block", message="Contains an email address."))
    if _PHONE_RE.search(text):
        issues.append(Issue(code="personal_data", severity="block", message="Contains a phone number."))
    for term in _banned_terms(banned_terms):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lower):
            issues.append(Issue(code="banned_term", severity="block", message=f'Uses the banned term "{term}".'))
    if "bluesky" in channels and len(text) > BLUESKY_MAX_CHARS:
        issues.append(Issue(code="too_long", severity="block",
                            message=f"{len(text)} characters; Bluesky posts are limited to {BLUESKY_MAX_CHARS}."))

    for pattern in _ABSOLUTE_CLAIMS + _REGULATED_CLAIMS.get(domain_category, []):
        found = re.search(pattern, lower)
        if found:
            issues.append(Issue(code="claim", severity="review",
                                message=f'"{found.group(0)}" is an absolute or regulated claim: check it can be substantiated.'))

    return GuardrailResult(issues=issues, disclaimer=DISCLAIMERS.get(domain_category))


def rewrite_directive(result: GuardrailResult) -> str:
    """Instructions for regenerating copy that hit a blocking issue."""
    problems = "; ".join(i.message for i in result.blocked)
    return f"The previous draft was rejected by brand-safety checks: {problems} Write new copy that avoids all of these."


SHORT_DISCLAIMERS = {
    "healthcare": "Not medical advice.",
    "finance_fintech": "Not financial advice. Capital at risk.",
    "fitness_wellness": "Results vary.",
}


def prepare_for_channel(
    copy_text: str, channel: str, *, domain_category: str = "other", cta_url: str | None = None,
    banned_terms: tuple[str, ...] | list[str] = (),
) -> tuple[str | None, str | None]:
    """Last check right before sending: (text to send, None) or (None, reason).

    Re-checks the final copy (blocking issues only) and adds the category's
    disclaimer: the short form on Bluesky when it still fits, the full form is
    added to emails by the email node."""
    result = check_creative(copy_text, domain_category=domain_category, channels=[channel], cta_url=cta_url,
                            banned_terms=banned_terms)
    if result.blocked:
        return None, "blocked by brand-safety checks: " + "; ".join(i.message for i in result.blocked)
    short = SHORT_DISCLAIMERS.get(domain_category)
    if channel == "bluesky" and short and len(copy_text) + 1 + len(short) <= BLUESKY_MAX_CHARS:
        return f"{copy_text} {short}", None
    return copy_text, None
