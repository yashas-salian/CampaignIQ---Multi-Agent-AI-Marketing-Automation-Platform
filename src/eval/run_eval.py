import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.capabilities.audience import generate_personas
from src.capabilities.feasibility import score_feasibility
from src.capabilities.idea_intake import normalize_idea
from src.eval.judge import feasibility_in_range, judge_personas

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
PASS_THRESHOLD = 0.6


def load_golden_set() -> list[dict]:
    return [json.loads(line) for line in GOLDEN_SET_PATH.read_text().splitlines() if line.strip()]


def run() -> float:
    entries = load_golden_set()
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

    return overall


def main() -> None:
    load_dotenv()
    overall = run()
    if overall < PASS_THRESHOLD:
        print(f"\nFAILED: overall score {overall:.0%} is below the {PASS_THRESHOLD:.0%} threshold")
        sys.exit(1)
    print("\nPASSED")


if __name__ == "__main__":
    main()
