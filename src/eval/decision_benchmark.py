"""Benchmark the decision engine on the fixed scenario suite.

    python -m src.eval.decision_benchmark          # print the table
    python -m src.eval.decision_benchmark --write  # also update docs/DECISION_ENGINE.md

Compares the engine with the simple rule it replaces, "launch whenever
feasibility ≥ 40", against hand-labelled expected decisions
(src/eval/decision_scenarios.py). Reported:
  * accuracy: share of scenarios where the decision matches the label;
  * unsafe launches: hard-blocked scenarios (prohibited product, unsupportable
    claim, broken link, banned word) that a rule would have launched;
  * launches into weak opportunities: scenarios labelled KILL/WAIT/
    INSUFFICIENT_EVIDENCE that a rule would have launched;
  * reproducibility: every scenario evaluated twice gives identical output.
"""
import json
import sys
from pathlib import Path

from src.capabilities.decision import POLICY_VERSION, evaluate
from src.eval.decision_scenarios import NOW, SCENARIOS

DOC = Path(__file__).resolve().parents[2] / "docs" / "DECISION_ENGINE.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
HARD = {"PROHIBITED_PRODUCT", "UNSUPPORTABLE_CLAIM", "INVALID_DESTINATION", "BANNED_TERM"}


def run() -> dict:
    rows = []
    for s in SCENARIOS:
        first, second = evaluate(s.inputs, now=NOW), evaluate(s.inputs, now=NOW)
        rows.append({
            "id": s.id, "expected": s.expected, "engine": first.decision, "baseline": first.baseline["decision"],
            "score": first.opportunity_score, "uncertainty": first.uncertainty, "reasons": first.reason_codes,
            "hard": bool(first.hard_blocks), "reproducible": first.model_dump() == second.model_dump(), "why": s.why,
        })
    n = len(rows)
    hard_rows = [r for r in rows if r["hard"]]
    weak_rows = [r for r in rows if r["expected"] in ("KILL", "WAIT", "INSUFFICIENT_EVIDENCE") and not r["hard"]]
    return {
        "policy_version": POLICY_VERSION,
        "scenarios": n,
        "engine_accuracy": sum(r["engine"] == r["expected"] for r in rows) / n,
        "baseline_accuracy": sum(r["baseline"] == r["expected"] for r in rows) / n,
        "engine_unsafe_launches": sum(r["engine"] in ("LAUNCH", "TEST_SMALL") for r in hard_rows),
        "baseline_unsafe_launches": sum(r["baseline"] == "LAUNCH" for r in hard_rows),
        "hard_scenarios": len(hard_rows),
        "engine_weak_launches": sum(r["engine"] in ("LAUNCH", "TEST_SMALL") for r in weak_rows),
        "baseline_weak_launches": sum(r["baseline"] == "LAUNCH" for r in weak_rows),
        "weak_scenarios": len(weak_rows),
        "reproducible": all(r["reproducible"] for r in rows),
        "rows": rows,
    }


def markdown(result: dict) -> str:
    pct = lambda x: f"{round(100 * x)}%"  # noqa: E731
    lines = [
        f"Policy `{result['policy_version']}`, {result['scenarios']} scenarios "
        "(`python -m src.eval.decision_benchmark`).",
        "",
        "| | Decision engine | Baseline: launch if feasibility ≥ 40 |",
        "|---|---|---|",
        f"| Matches the expected decision | **{pct(result['engine_accuracy'])}** | {pct(result['baseline_accuracy'])} |",
        f"| Launches a hard-blocked campaign (of {result['hard_scenarios']}) | **{result['engine_unsafe_launches']}** | {result['baseline_unsafe_launches']} |",
        f"| Spends on a weak opportunity (of {result['weak_scenarios']}) | **{result['engine_weak_launches']}** | {result['baseline_weak_launches']} |",
        f"| Same output on re-run | {'yes' if result['reproducible'] else 'NO'} | yes |",
        "",
        "| Scenario | Expected | Engine | Baseline | Score | Why (expected) |",
        "|---|---|---|---|---|---|",
    ]
    for r in result["rows"]:
        mark = "" if r["engine"] == r["expected"] else " ✗"
        lines.append(f"| {r['id']} | {r['expected']} | {r['engine']}{mark} | {r['baseline']} | "
                     f"{'—' if r['score'] is None else r['score']} | {r['why']} |")
    return "\n".join(lines)


def main() -> None:
    result = run()
    table = markdown(result)
    print(table)
    if "--json" in sys.argv:
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    if "--write" in sys.argv:
        text = DOC.read_text(encoding="utf-8")
        head, rest = text.split(START, 1)
        tail = rest.split(END, 1)[1]
        DOC.write_text(f"{head}{START}\n{table}\n{END}{tail}", encoding="utf-8")
        print(f"\nwrote {DOC}")


if __name__ == "__main__":
    main()
