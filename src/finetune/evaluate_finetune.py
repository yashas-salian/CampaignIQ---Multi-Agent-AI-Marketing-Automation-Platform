"""M7 evaluation: teacher vs untuned base vs fine-tuned student, side by side.

Two measurements, kept separate on purpose:
  * golden  -- the 18 hand-labelled ideas in src/eval/golden_set.jsonl. Human
               labels, so this is the only fair *accuracy* comparison of all three.
  * heldout -- src/finetune/data/test.jsonl. Its labels come from the teacher, so
               it measures *agreement with the teacher* (how faithfully the
               student copies it). The teacher scores 100% here by construction
               and is not re-run on it.

Usage:
  .venv/Scripts/python.exe -m src.finetune.evaluate_finetune \
      --base  src/finetune/models/qwen2.5-1.5b-instruct-q4_k_m.gguf \
      --tuned src/finetune/models/marketingos-domain-q4_k_m.gguf
Either model flag may be omitted to skip it. Writes src/finetune/reports/<timestamp>.json.
"""
import argparse
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.capabilities.idea_intake import normalize_idea
from src.finetune.generate_dataset import DATA_DIR, GOLDEN

REPORTS = Path(__file__).parent / "reports"
TEACHER_COST_NOTE = "Groq free tier: no per-call cost, but rate-limited and an external dependency"


def _rows(path: Path, idea_key: str, label_key: str) -> list[dict]:
    return [
        {"idea": r[idea_key], "label": r[label_key]}
        for r in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    ]


def _score(name: str, rows: list[dict], predict) -> dict:
    hits, invalid, errors, confusions, times = 0, 0, 0, Counter(), []
    for row in rows:
        start = time.perf_counter()
        try:
            pred = predict(row["idea"])
        except Exception as exc:  # one failure is a data point, not a crash
            errors += 1
            print(f"  ! {name}: {str(exc)[:80]}")
            continue
        times.append((time.perf_counter() - start) * 1000)
        invalid += pred is None
        if pred == row["label"]:
            hits += 1
        else:
            confusions[f"{row['label']} -> {pred}"] += 1
    n = len(rows)
    return {
        "n": n,
        "correct": hits,
        "accuracy": round(hits / n, 4) if n else None,
        "invalid_outputs": invalid,
        "errors": errors,
        "median_ms_per_idea": round(sorted(times)[len(times) // 2], 1) if times else None,
        "top_confusions": confusions.most_common(5),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base", help="untuned base model GGUF")
    parser.add_argument("--tuned", help="fine-tuned GGUF from train_lora.ipynb")
    parser.add_argument("--skip-teacher", action="store_true", help="don't call Groq for the golden comparison")
    args = parser.parse_args()
    load_dotenv()

    golden = _rows(GOLDEN, "idea", "expected_domain")
    test_path = DATA_DIR / "test.jsonl"
    # The held-out set exists once generate_dataset.py has finished; golden alone is still a valid run.
    heldout = _rows(test_path, "idea", "label") if test_path.exists() else []
    if not heldout:
        print(f"note: {test_path.name} not found yet -> golden set only")

    models: dict[str, callable] = {}
    if not args.skip_teacher:
        models["teacher (gpt-oss-120b via Groq)"] = lambda idea: normalize_idea(idea, use_local=False).domain_category
    if args.base or args.tuned:
        from src.finetune.local_classifier import classify

        if args.base:
            models[f"base ({Path(args.base).name})"] = lambda idea, p=args.base: classify(idea, p)[0]
        if args.tuned:
            models[f"fine-tuned ({Path(args.tuned).name})"] = lambda idea, p=args.tuned: classify(idea, p)[0]

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "golden": {}, "heldout_agreement_with_teacher": {}}
    for name, predict in models.items():
        print(f"[{name}] golden ({len(golden)})…", flush=True)
        report["golden"][name] = _score(name, golden, predict)
        if heldout and not name.startswith("teacher"):
            print(f"[{name}] held-out ({len(heldout)})…", flush=True)
            report["heldout_agreement_with_teacher"][name] = _score(name, heldout, predict)
    report["notes"] = {
        "golden": "human labels; the fair accuracy comparison",
        "heldout": "teacher labels; measures fidelity to the teacher (teacher = 100% by construction)",
        "teacher_cost": TEACHER_COST_NOTE,
    }

    print("\n=== M7 results ===")
    print(f"{'model':<52} {'golden acc':>11} {'held-out agree':>15} {'ms/idea':>9}")
    for name in models:
        g = report["golden"][name]
        h = report["heldout_agreement_with_teacher"].get(name)
        print(
            f"{name:<52} {g['accuracy']:>10.0%} "
            f"{(f'{h['accuracy']:.0%}' if h else 'n/a (labels)'):>15} {str(g['median_ms_per_idea']):>9}"
        )

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nreport -> {out}")


if __name__ == "__main__":
    main()
