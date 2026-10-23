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
    # The compliance radar's four areas: safety | claims | readability | accessibility.
    category: str = "safety"
    fix: str | None = None  # one concrete suggestion for the approver


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
    language: str = "en",
) -> GuardrailResult:
    text = copy_text or ""
    lower = text.lower()
    issues: list[Issue] = []

    if not text.strip():
        issues.append(Issue(code="empty", severity="block", message="The copy is empty.", fix="Regenerate the round's copy."))

    allowed_host = _host(cta_url) if cta_url else None
    for match in _URL_RE.findall(text):
        host = _host(match)
        if not allowed_host or not (host == allowed_host or host.endswith("." + allowed_host)):
            issues.append(Issue(code="foreign_link", severity="block",
                                message=f"Links to {host}, which isn't the campaign's own link.",
                                fix="Remove the link; the call-to-action link is added automatically."))
    if _EMAIL_RE.search(text):
        issues.append(Issue(code="personal_data", severity="block", message="Contains an email address.",
                            fix="Remove the address; replies go through the call-to-action link."))
    if _PHONE_RE.search(text):
        issues.append(Issue(code="personal_data", severity="block", message="Contains a phone number.",
                            fix="Remove the number; contact details belong on the landing page."))
    for term in _banned_terms(banned_terms):
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", lower):
            issues.append(Issue(code="banned_term", severity="block", message=f'Uses the banned term "{term}".',
                                fix=f'Replace "{term}" with neutral wording.'))
    if "bluesky" in channels and len(text) > BLUESKY_MAX_CHARS:
        issues.append(Issue(code="too_long", severity="block",
                            message=f"{len(text)} characters; Bluesky posts are limited to {BLUESKY_MAX_CHARS}.",
                            fix=f"Cut at least {len(text) - BLUESKY_MAX_CHARS} characters: keep one benefit and the call to action."))

    for pattern in _ABSOLUTE_CLAIMS + _REGULATED_CLAIMS.get(domain_category, []):
        found = re.search(pattern, lower)
        if found:
            issues.append(Issue(code="claim", severity="review", category="claims",
                                message=f'"{found.group(0)}" is an absolute or regulated claim: check it can be substantiated.',
                                fix=_CLAIM_FIX))
    found = _COMPARATIVE_RE.search(lower)
    if found:
        issues.append(Issue(code="comparative", severity="review", category="claims",
                            message=f'"{found.group(0)}" is a comparative claim that ad platforms ask you to back up.',
                            fix="Cite a source next to it, or rephrase as your own view (e.g. \"our favourite way to…\")."))

    issues += _readability(text, language) + _accessibility(text)
    return GuardrailResult(issues=issues, disclaimer=DISCLAIMERS.get(domain_category))


# ---------- Compliance radar: advice for the approver, never blocking ----------

_CLAIM_FIX = 'Soften it to something provable (e.g. "designed to…", "helps you…") or add evidence next to it.'
_COMPARATIVE_RE = re.compile(r"\b(the best|best[- ]in[- ]class|cheapest|lowest price|fastest|unbeatable|world'?s (best|first|leading)|better than (any|all))\b")
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
_SHOUT_RE = re.compile(r"\b[A-Z]{4,}\b")
_HASHTAG_RE = re.compile(r"#([a-z]{2,}[a-z]+)\b")
_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]*")


def _syllables(word: str) -> int:
    word = word.lower().strip("'")
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups) - (1 if word.endswith("e") and len(groups) > 1 else 0)
    return max(1, count)


def flesch_reading_ease(text: str) -> float | None:
    """Flesch reading ease (0-100, higher is easier) for English text; None if too short to judge."""
    words = re.findall(r"[A-Za-z']+", text)
    sentences = [s for s in _SENTENCE_RE.findall(text) if re.search(r"[A-Za-z]", s)]
    if len(words) < 12 or not sentences:
        return None
    syllables = sum(_syllables(w) for w in words)
    return round(206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words)), 1)


def _readability(text: str, language: str) -> list[Issue]:
    # The formulas are English-specific; other languages skip this part of the radar.
    if language != "en":
        return []
    issues: list[Issue] = []
    score = flesch_reading_ease(text)
    if score is not None and score < 50:
        issues.append(Issue(code="hard_to_read", severity="review", category="readability",
                            message=f"Hard to read: reading-ease score {max(0, score):.0f}/100 (aim for 60+ in ads).",
                            fix="Use shorter sentences and everyday words; one idea per sentence."))
    longest = max((len(s.split()) for s in _SENTENCE_RE.findall(text)), default=0)
    if longest > 28:
        issues.append(Issue(code="long_sentence", severity="review", category="readability",
                            message=f"One sentence runs {longest} words; people skim ads.",
                            fix="Split it in two, keeping the benefit first."))
    return issues


def _accessibility(text: str) -> list[Issue]:
    issues: list[Issue] = []
    emoji = _EMOJI_RE.findall(text)
    if len(emoji) > 3:
        issues.append(Issue(code="emoji_overload", severity="review", category="accessibility",
                            message=f"{len(emoji)} emoji: screen readers read each one aloud.",
                            fix="Keep at most two or three, and never in the middle of a sentence."))
    shouting = _SHOUT_RE.findall(text)
    if shouting:
        issues.append(Issue(code="all_caps", severity="review", category="accessibility",
                            message=f"All-caps words ({', '.join(shouting[:3])}) read as shouting, and some screen readers spell them out.",
                            fix="Use sentence case; add emphasis with word choice instead."))
    hashtags = [h for h in _HASHTAG_RE.findall(text) if len(h) >= 8]
    if hashtags:
        issues.append(Issue(code="hashtag_case", severity="review", category="accessibility",
                            message=f"#{hashtags[0]} is hard for screen readers to split into words.",
                            fix="Write hashtags in CamelCase, capitalising each word (e.g. #BudgetingApp, not #budgetingapp)."))
    return issues


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
