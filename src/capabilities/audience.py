import re
from typing import Literal

from pydantic import BaseModel

from src.capabilities.feasibility import FeasibilityResult
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence

AgeBracket = Literal["18-24", "25-34", "35-44", "45-54", "55+"]
IncomeTier = Literal["low", "mid", "high"]

_AGE_BRACKETS = ("18-24", "25-34", "35-44", "45-54", "55+")
_INCOME_TIERS = ("low", "mid", "high")

# Who the persona is, visually: picks the 3D figure shown on persona cards
# (frontend/public/personas/<archetype>-<gender>.webp). Must match render_personas.py.
ARCHETYPES = (
    "teacher", "doctor", "nurse", "student", "developer", "chef", "athlete", "parent", "retiree",
    "professional", "entrepreneur", "designer", "farmer", "traveler", "gamer", "scientist",
    "tradesperson", "finance", "creator", "general",
)

# Keyword fallback for personas written before archetypes existed, or when the
# model's answer isn't on the list. First match wins, so specific roles go first.
_ARCHETYPE_HINTS = [
    ("nurse", ("nurse", "nursing")),
    ("doctor", ("doctor", "physician", "surgeon", "dentist", "medical", "clinician")),
    ("teacher", ("teacher", "educator", "professor", "tutor", "lecturer")),
    ("student", ("student", "undergrad", "college", "university", "school")),
    ("developer", ("developer", "engineer", "programmer", "software", "coder", "devops")),
    ("chef", ("chef", "cook", "baker", "restaurant", "culinary")),
    ("athlete", ("athlete", "runner", "fitness", "gym", "yoga", "sport", "cyclist")),
    ("parent", ("parent", "mother", "father", "mom", "dad", "mum")),
    ("retiree", ("retiree", "retired", "pensioner", "senior", "grandparent")),
    ("scientist", ("scientist", "researcher", "lab", "biologist", "chemist")),
    ("designer", ("designer", "artist", "creative", "illustrator", "architect")),
    ("farmer", ("farmer", "agricultur", "grower")),
    ("traveler", ("traveler", "traveller", "backpacker", "tourist", "nomad")),
    ("gamer", ("gamer", "gaming", "esports")),
    ("tradesperson", ("construction", "electrician", "plumber", "mechanic", "tradesperson", "carpenter")),
    ("finance", ("finance", "accountant", "analyst", "banker", "investor")),
    ("creator", ("creator", "influencer", "youtuber", "streamer", "blogger")),
    ("entrepreneur", ("entrepreneur", "founder", "business owner", "shop owner", "freelancer", "self-employed")),
    ("professional", ("professional", "manager", "executive", "consultant", "office", "corporate")),
]


# The figure's gender must match the persona's, so it comes from the model,
# which wrote the persona. "unspecified" (no figure, initials instead) when the
# model gives neither and the description has no pronouns to go on.
GENDERS = ("female", "male", "unspecified")
_FEMALE = re.compile(r"\b(she|her|hers|herself|woman|women|mother|mom|mum|wife|girl|grandmother)\b")
_MALE = re.compile(r"\b(he|him|his|himself|man|men|father|dad|husband|boy|grandfather)\b")


def guess_gender(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    female, male = len(_FEMALE.findall(blob)), len(_MALE.findall(blob))
    if female > male:
        return "female"
    if male > female:
        return "male"
    return "unspecified"


def guess_archetype(*texts: str) -> str:
    blob = " ".join(t for t in texts if t).lower()
    for archetype, words in _ARCHETYPE_HINTS:
        if any(w in blob for w in words):
            return archetype
    return "general"


class Persona(BaseModel):
    name: str
    demographics: str
    psychographics: str
    channel_fit: str
    messaging_angle: str
    age_bracket: AgeBracket
    income_tier: IncomeTier
    archetype: str = "general"
    gender: str = "unspecified"


def _coerce_to_str(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value)


def _coerce_literal(value: object, allowed: tuple[str, ...], default: str) -> str:
    # Bandit context features must be exactly one of a fixed enum -- fall back
    # to a default bucket rather than crashing on an imprecise free-tier LLM value.
    text = _coerce_to_str(value).strip()
    return text if text in allowed else default


def generate_personas(
    idea: str,
    feasibility: FeasibilityResult,
    *,
    n: int = 3,
    user_id: str | None = None,
    target_language: str = "en",
) -> list[Persona]:
    prompt, system = PROMPTS["audience.personas"].render(
        idea=fence(idea, "user_idea"),
        rationale=fence(feasibility.rationale, "feasibility_rationale"),
        n=n,
        language=language_name(target_language),
        age_brackets=list(_AGE_BRACKETS),
        income_tiers=list(_INCOME_TIERS),
        archetypes=list(ARCHETYPES),
        genders=["female", "male"],
    )
    personas_raw = generate_json(get_llm(user_id), prompt, system=system)
    return [
        Persona(
            name=_coerce_to_str(p["name"]),
            demographics=_coerce_to_str(p["demographics"]),
            psychographics=_coerce_to_str(p["psychographics"]),
            channel_fit=_coerce_to_str(p["channel_fit"]),
            messaging_angle=_coerce_to_str(p["messaging_angle"]),
            age_bracket=_coerce_literal(p.get("age_bracket"), _AGE_BRACKETS, "25-34"),
            income_tier=_coerce_literal(p.get("income_tier"), _INCOME_TIERS, "mid"),
            archetype=_archetype(p),
            gender=_gender(p),
        )
        for p in personas_raw
    ]


def _archetype(p: dict) -> str:
    # Trust the model's pick when it is on the list (any case); "general" or an
    # off-list answer falls back to the keyword guess, so a "Nurse Priya" the
    # model left as "general" still gets the nurse figure.
    picked = _coerce_to_str(p.get("archetype", "")).strip().lower()
    if picked in ARCHETYPES and picked != "general":
        return picked
    return guess_archetype(_coerce_to_str(p.get("name", "")), _coerce_to_str(p.get("demographics", "")))


def _gender(p: dict) -> str:
    # Never guessed from the name: the model states it, else the pronouns in
    # the description decide, else "unspecified".
    picked = _coerce_to_str(p.get("gender", "")).strip().lower()
    if picked in ("female", "male"):
        return picked
    return guess_gender(*(_coerce_to_str(p.get(k, "")) for k in ("demographics", "psychographics", "messaging_angle")))
