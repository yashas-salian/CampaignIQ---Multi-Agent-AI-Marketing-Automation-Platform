import json
from pathlib import Path

import pytest

from src.capabilities import audience
from src.capabilities.audience import ARCHETYPES, guess_archetype, guess_gender
from src.capabilities.feasibility import FeasibilityResult

FIGURES = Path(__file__).resolve().parents[2] / "frontend" / "public" / "personas"
ARCHETYPES_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "archetypes.ts"


def _persona(**overrides):
    base = {
        "name": "Asha",
        "demographics": "32, lives in Pune",
        "psychographics": "values time",
        "channel_fit": "instagram",
        "messaging_angle": "save hours",
        "age_bracket": "25-34",
        "income_tier": "mid",
    }
    return {**base, **overrides}


class TestGuessArchetype:
    @pytest.mark.parametrize(
        ("texts", "expected"),
        [
            (("Teacher Tom", "45, high-school educator"), "teacher"),
            (("Dr. Mehta", "surgeon at a city hospital"), "doctor"),
            (("Priya", "ICU nurse, night shifts"), "nurse"),  # nurse wins over the medical words
            (("Kai", "college student, 20"), "student"),
            (("Sam", "freelance graphic designer"), "designer"),
            (("Ravi", "software engineer"), "developer"),
            (("Lena", "62, retired librarian"), "retiree"),
            (("Alex", "lives downtown"), "general"),
        ],
    )
    def test_keywords(self, texts, expected):
        assert guess_archetype(*texts) == expected

    def test_ignores_empty_parts(self):
        assert guess_archetype("", None, "Personal TRAINER at a gym") == "athlete"


class TestGeneratedArchetype:
    def _run(self, monkeypatch, fake_llm, personas):
        monkeypatch.setattr(audience, "get_llm", lambda user_id=None: fake_llm(json.dumps(personas)))
        result = audience.generate_personas("idea", FeasibilityResult(score=50, rationale="ok", signals={}))
        return [p.archetype for p in result]

    def test_model_pick_is_kept_case_insensitively(self, monkeypatch, fake_llm):
        assert self._run(monkeypatch, fake_llm, [_persona(archetype="Chef")]) == ["chef"]

    def test_off_list_or_missing_falls_back_to_keywords(self, monkeypatch, fake_llm):
        personas = [
            _persona(archetype="wizard", demographics="primary school teacher"),
            _persona(demographics="hospital physician"),
            _persona(archetype=None),
        ]
        assert self._run(monkeypatch, fake_llm, personas) == ["teacher", "doctor", "general"]

    def test_general_is_upgraded_when_keywords_say_more(self, monkeypatch, fake_llm):
        assert self._run(monkeypatch, fake_llm, [_persona(name="Nurse Priya", archetype="general")]) == ["nurse"]


class TestGender:
    @pytest.mark.parametrize(
        ("texts", "expected"),
        [
            (("She runs a bakery", "her customers love her"), "female"),
            (("He is a nurse", "his shifts are long"), "male"),
            (("A mother of two",), "female"),
            (("Lives in Pune, 34, freelance designer",), "unspecified"),  # no pronouns: no guess
            (("Others say there is hesitation here",), "unspecified"),  # 'her'/'he' inside words don't count
        ],
    )
    def test_pronouns(self, texts, expected):
        assert guess_gender(*texts) == expected

    def test_model_gender_wins_and_name_is_never_used(self, monkeypatch, fake_llm):
        personas = [
            _persona(name="Priya", gender="Male"),  # the model's statement wins, any case
            _persona(name="Priya", demographics="34, he works nights"),  # pronouns, not the name
            _persona(name="Priya"),  # nothing to go on
        ]
        monkeypatch.setattr(audience, "get_llm", lambda user_id=None: fake_llm(json.dumps(personas)))
        result = audience.generate_personas("idea", FeasibilityResult(score=50, rationale="ok", signals={}))
        assert [p.gender for p in result] == ["male", "male", "unspecified"]


def test_every_archetype_has_a_female_and_male_figure():
    missing = [f"{a}-{g}" for a in ARCHETYPES for g in ("female", "male") if not (FIGURES / f"{a}-{g}.webp").exists()]
    assert not missing, f"render them: python frontend/scripts/render_personas.py {' '.join(missing)}"


def test_frontend_list_matches_backend():
    ts = ARCHETYPES_TS.read_text(encoding="utf-8")
    block = ts[ts.index("ARCHETYPES = [") : ts.index("] as const")]
    assert [w.strip(" '\n") for w in block.split("[", 1)[1].split(",") if w.strip(" '\n")] == list(ARCHETYPES)
