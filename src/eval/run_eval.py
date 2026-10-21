import argparse
import json
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from src.capabilities.audience import generate_personas
from src.capabilities.feasibility import score_feasibility
from src.capabilities.idea_intake import normalize_idea
from src.eval.judge import feasibility_in_range, judge_personas

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
BASELINE_PATH = Path(__file__).parent / "baseline.json"
PASS_THRESHOLD = 0.6
# Regression gate: no metric may fall more than this far below the accepted baseline.
REGRESSION_TOLERANCE = 0.05


def load_golden_set() -> list[dict]:
    return [json.loads(line) for line in GOLDEN_SET_PATH.read_text().splitlines() if line.strip()]


def run() -> dict[str, float]:
    entries = load_golden_set()
    # Say which classifier the domain column is measuring (M7 local model or the
    # LLM fallback); the classifier's own messages are INFO and not printed here.
    from src.providers.free.local_domain_classifier import available

    print(f"domain classifier: {'fine-tuned local model (M7)' if available() else 'LLM (Groq)'}", flush=True)
    domain_hits = 0
    feasibility_hits = 0
    persona_scores = []

    for entry in entries:
        normalized = normalize_idea(entry["idea"])
        domain_match = normalized.domain_category == entry["expected_domain"]
        domain_hits += domain_match

        feasibility = score_feasibility(normalized.idea)
        in_range = feasibility_in_range(feasibility.score, entry["expected_min"], entry["expected_max"])
        feasibility_hits += in_range

        personas = generate_personas(normalized.idea, feasibility, n=3)
        judgement = judge_personas(normalized.idea, personas)
        persona_scores.append(judgement.score)

        print(
            f"[{'OK' if domain_match else 'FAIL'}] domain={normalized.domain_category} "
            f"(expected {entry['expected_domain']}) | "
            f"[{'OK' if in_range else 'FAIL'}] feasibility={feasibility.score} "
            f"(expected {entry['expected_min']}-{entry['expected_max']}) | "
            f"persona_score={judgement.score}/5 -- {entry['idea'][:60]}"
        )

    n = len(entries)
    domain_accuracy = domain_hits / n
    feasibility_accuracy = feasibility_hits / n
    persona_quality = (sum(persona_scores) / len(persona_scores)) / 5
    overall = (domain_accuracy + feasibility_accuracy + persona_quality) / 3

    print("\n--- Eval Report ---")
    print(f"Domain classification accuracy: {domain_accuracy:.0%} ({domain_hits}/{n})")
    print(f"Feasibility-in-range accuracy:   {feasibility_accuracy:.0%} ({feasibility_hits}/{n})")
    print(
        f"Average persona quality:         {persona_quality:.0%} "
        f"(avg {sum(persona_scores) / len(persona_scores):.1f}/5)"
    )
    print(f"Overall score:                   {overall:.0%} (threshold {PASS_THRESHOLD:.0%})")

    from src.prompts import PROMPTS

    print("Prompts:", ", ".join(sorted(p.ref for p in PROMPTS.values())))
    return {
        "domain_accuracy": domain_accuracy,
        "feasibility_accuracy": feasibility_accuracy,
        "persona_quality": persona_quality,
        "overall": overall,
    }


def regressions(scores: dict[str, float]) -> list[str]:
    """Metrics that dropped more than REGRESSION_TOLERANCE below the accepted baseline."""
    if not BASELINE_PATH.exists():
        return []
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))["metrics"]
    return [
        f"{name}: {scores[name]:.0%} vs baseline {base:.0%}"
        for name, base in baseline.items()
        if name in scores and scores[name] < base - REGRESSION_TOLERANCE
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden-set eval with a regression gate.")
    parser.add_argument("--update-baseline", action="store_true", help="accept this run's scores as the new baseline")
    args = parser.parse_args()
    load_dotenv()
    from src.observability import init

    init("eval")
    scores = run()
    if args.update_baseline:
        from src.prompts import PROMPTS

        BASELINE_PATH.write_text(json.dumps({
            "accepted": date.today().isoformat(),
            "note": "Update with `python -m src.eval.run_eval --update-baseline` after an intended change.",
            "prompts": sorted(p.ref for p in PROMPTS.values()),
            "metrics": {k: round(v, 3) for k, v in scores.items()},
        }, indent=2) + "\n", encoding="utf-8")
        print(f"\nBaseline updated: {BASELINE_PATH.name}")
        return
    failures = []
    if scores["overall"] < PASS_THRESHOLD:
        failures.append(f"overall score {scores['overall']:.0%} is below the {PASS_THRESHOLD:.0%} threshold")
    failures += [f"regression, {r}" for r in regressions(scores)]
    if failures:
        print("\nFAILED:\n- " + "\n- ".join(failures))
        sys.exit(1)
    print("\nPASSED")


if __name__ == "__main__":
    main()
