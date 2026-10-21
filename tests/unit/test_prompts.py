import json
import re
import string
from pathlib import Path

import pytest

from src.prompts import PROMPTS, current_prompt
from src.prompts.__main__ import FINGERPRINTS
from src.security.prompt_guard import GUARD

RECORDED = json.loads(Path(FINGERPRINTS).read_text(encoding="utf-8"))


@pytest.mark.parametrize("pid", sorted(PROMPTS))
def test_prompt_changes_come_with_a_version_bump(pid):
    prompt, recorded = PROMPTS[pid], RECORDED.get(pid)
    assert recorded, f"{pid} is new: run `python -m src.prompts --update-fingerprints`"
    if prompt.fingerprint != recorded["fingerprint"]:
        assert prompt.version != recorded["version"], (
            f"{pid}'s text changed but its version is still {prompt.version}: bump it, add a CHANGELOG line, "
            "then run `python -m src.prompts --update-fingerprints`"
        )
        pytest.fail(f"{pid} was bumped to {prompt.version}: run `python -m src.prompts --update-fingerprints`")


def test_no_stale_fingerprints():
    assert set(RECORDED) == set(PROMPTS)


@pytest.mark.parametrize("pid", sorted(PROMPTS))
def test_versions_are_semver_and_templates_render(pid):
    prompt = PROMPTS[pid]
    assert re.fullmatch(r"\d+\.\d+\.\d+", prompt.version)
    fields = {name for _, name, _, _ in string.Formatter().parse(prompt.template) if name}
    text, system = prompt.render(**{f: f"<{f}>" for f in fields})
    assert "{" not in text.replace("<", "").replace(">", "") or "{" in prompt.template.replace("{{", "")
    assert system.endswith(GUARD) is prompt.guard
    assert current_prompt.get() == prompt.ref


def test_user_facing_prompts_all_carry_the_injection_rule():
    assert [p.id for p in PROMPTS.values() if not p.guard] == ["eval.judge_personas"]


def test_eval_regression_gate(tmp_path, monkeypatch):
    from src.eval import run_eval

    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"metrics": {"domain_accuracy": 0.83, "overall": 0.67}}), encoding="utf-8")
    monkeypatch.setattr(run_eval, "BASELINE_PATH", baseline)
    assert run_eval.regressions({"domain_accuracy": 0.80, "overall": 0.66}) == []  # within 5 points
    assert run_eval.regressions({"domain_accuracy": 0.72, "overall": 0.66}) == ["domain_accuracy: 72% vs baseline 83%"]
