"""M7 weekly retrain: prepare data, gate on quality, publish the winner.

Driven by .github/workflows/retrain-domain-model.yml; training itself runs on
a free Kaggle GPU (src/finetune/kaggle/train_kernel.py).

  prepare   synthetic train/val (committed) + human Gate-1 corrections
            (domain_corrections). Skips the week when there are too few new
            corrections. ~1 in 5 corrections is held back for the quality gate.
  evaluate  candidate vs current model on: the golden set (human labels),
            held-out corrections (human labels), held-out synthetic test
            (agreement with the teacher). Promote only if not worse.
  promote   upload the GGUF + training_meta.json to the private HF repo.

Real corrections are users' content: the Kaggle dataset/kernel are private and
the model only ever goes to the private Hugging Face repo.
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.finetune.generate_dataset import DATA_DIR, GOLDEN
from src.finetune.prompt import SYSTEM
from src.providers.free.local_domain_classifier import DEFAULT_FILE

MIN_NEW_CORRECTIONS = 30
CORRECTION_WEIGHT = 3  # human labels are scarce and better than the teacher's
HOLDOUT_EVERY = 5  # ~20% of corrections are held back for the gate
HELDOUT_SLACK = 0.03  # teacher-agreement may dip slightly when humans disagree with the teacher
META_FILE = "training_meta.json"


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _gh_output(**values) -> None:
    """Expose step outputs to GitHub Actions (no-op locally)."""
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")
    print(" ".join(f"{k}={v}" for k, v in values.items()))


def _summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")
    print(markdown)


def _current_meta() -> dict:
    """training_meta.json of the published model (absent for the first, notebook-trained model)."""
    repo = os.environ.get("DOMAIN_MODEL_HF_REPO")
    if not repo:
        return {}
    try:
        from huggingface_hub import hf_hub_download

        path = hf_hub_download(repo, META_FILE, token=os.environ.get("HF_TOKEN") or None)
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_holdout(row_id: str) -> bool:
    return int(hashlib.sha1(row_id.encode()).hexdigest()[:8], 16) % HOLDOUT_EVERY == 0


def _corrections() -> list[dict]:
    from src.db.supabase_client import get_client  # service role: reads every user's rows

    rows = (
        get_client()
        .table("domain_corrections")
        .select("id,idea,corrected_domain,created_at")
        .order("created_at")
        .execute()
        .data
    )
    return [r for r in rows if r["corrected_domain"] in DOMAIN_CATEGORIES and (r["idea"] or "").strip()]


def prepare(out: Path, force: bool) -> None:
    corrections = _corrections()
    last = _current_meta().get("trained_at")
    new = [c for c in corrections if not last or c["created_at"] > last]
    _summary(f"### Domain model retrain\n- corrections total: **{len(corrections)}**, new since last training: **{len(new)}** (threshold {MIN_NEW_CORRECTIONS})")
    if len(new) < MIN_NEW_CORRECTIONS and not force:
        _summary("- **skipped**: not enough new human corrections this week")
        _gh_output(should_train="false")
        return

    holdout = [c for c in corrections if _is_holdout(c["id"])]
    usable = [c for c in corrections if not _is_holdout(c["id"])]
    human = [{"idea": c["idea"].strip(), "label": c["corrected_domain"], "source": "correction"} for c in usable]

    train = _jsonl(DATA_DIR / "train.jsonl")
    # A human correction overrides any teacher label for the same idea text.
    corrected = {h["idea"].casefold() for h in human}
    train = [r for r in train if r["idea"].casefold() not in corrected] + human * CORRECTION_WEIGHT

    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "train.jsonl", train)
    _write_jsonl(out / "val.jsonl", _jsonl(DATA_DIR / "val.jsonl"))
    (out / "prompt.json").write_text(json.dumps({"system": SYSTEM, "categories": list(DOMAIN_CATEGORIES)}), encoding="utf-8")
    # The held-back corrections stay here for the gate; they never go to Kaggle.
    holdout_path = out.parent / "corrections_holdout.jsonl"
    _write_jsonl(holdout_path, [{"idea": c["idea"].strip(), "label": c["corrected_domain"]} for c in holdout])
    (out.parent / "prepare_meta.json").write_text(
        json.dumps({"corrections_total": len(corrections), "corrections_used": len(human), "holdout": len(holdout)}), encoding="utf-8"
    )
    _summary(f"- training rows: **{len(train)}** (synthetic + {len(human)} corrections ×{CORRECTION_WEIGHT}), held-back corrections: **{len(holdout)}**")
    _gh_output(should_train="true")


def _accuracy(rows: list[dict], model: str) -> float | None:
    from src.finetune.local_classifier import classify

    if not rows:
        return None
    return sum(classify(r["idea"], model)[0] == r["label"] for r in rows) / len(rows)


def evaluate(candidate: str, current: str | None, holdout_path: Path, report_path: Path) -> None:
    golden = [{"idea": r["idea"], "label": r["expected_domain"]} for r in _jsonl(GOLDEN)]
    heldout = _jsonl(DATA_DIR / "test.jsonl")
    holdout = _jsonl(holdout_path) if holdout_path.exists() else []

    def scores(model: str) -> dict:
        return {"golden": _accuracy(golden, model), "corrections": _accuracy(holdout, model), "heldout": _accuracy(heldout, model)}

    cand = scores(candidate)
    curr = scores(current) if current and Path(current).is_file() else None
    if curr is None:
        promote, why = True, "no current model to compare against"
    else:
        checks = [cand["golden"] >= curr["golden"], cand["heldout"] >= curr["heldout"] - HELDOUT_SLACK]
        if holdout:
            checks.append(cand["corrections"] >= curr["corrections"])
        promote = all(checks)
        why = "not worse on every gate" if promote else "worse than the current model on at least one gate"

    fmt = lambda v: "n/a" if v is None else f"{v:.0%}"  # noqa: E731
    lines = ["| model | golden (human) | held-back corrections (human) | held-out (teacher agreement) |", "|---|---|---|---|"]
    if curr:
        lines.append(f"| current | {fmt(curr['golden'])} | {fmt(curr['corrections'])} | {fmt(curr['heldout'])} |")
    lines.append(f"| candidate | {fmt(cand['golden'])} | {fmt(cand['corrections'])} | {fmt(cand['heldout'])} |")
    _summary("\n".join(lines) + f"\n\n**{'PROMOTE' if promote else 'KEEP CURRENT'}**: {why}")
    report_path.write_text(json.dumps({"candidate": cand, "current": curr, "promote": promote, "holdout_size": len(holdout)}, indent=2), encoding="utf-8")
    _gh_output(promote=str(promote).lower())


def promote(candidate: str, report_path: Path, prepare_meta_path: Path) -> None:
    from huggingface_hub import HfApi

    repo = os.environ["DOMAIN_MODEL_HF_REPO"]
    api = HfApi(token=os.environ.get("HF_WRITE_TOKEN") or os.environ["HF_TOKEN"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    prep = json.loads(prepare_meta_path.read_text(encoding="utf-8")) if prepare_meta_path.exists() else {}
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "base_model": "Qwen2.5-1.5B-Instruct + LoRA r16 (Unsloth, Kaggle GPU)",
        "data": {"synthetic": "src/finetune/data/train.jsonl", **prep},
        "metrics": report["candidate"],
        "previous_metrics": report["current"],
    }
    api.upload_file(path_or_fileobj=candidate, path_in_repo=DEFAULT_FILE, repo_id=repo, commit_message="Weekly retrain: promote candidate")
    commit = api.upload_file(path_or_fileobj=json.dumps(meta, indent=2).encode(), path_in_repo=META_FILE, repo_id=repo, commit_message="Weekly retrain: training metadata")
    # Pin the new commit as active (the previous one stays one command away:
    # `python -m src.finetune.deployments rollback`).
    try:
        from src.finetune.deployments import record_promotion

        record_promotion(commit.oid)
    except Exception as exc:
        print(f"model registry not updated ({exc}); the latest commit is served by default")
    _summary(f"- **published** to `{repo}` as `{DEFAULT_FILE}`")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", type=Path, default=Path("retrain/kaggle-data"))
    p.add_argument("--force", action="store_true", help="train even below the correction threshold")
    e = sub.add_parser("evaluate")
    e.add_argument("--candidate", required=True)
    e.add_argument("--current")
    e.add_argument("--holdout", type=Path, default=Path("retrain/corrections_holdout.jsonl"))
    e.add_argument("--report", type=Path, default=Path("retrain/gate_report.json"))
    pr = sub.add_parser("promote")
    pr.add_argument("--candidate", required=True)
    pr.add_argument("--report", type=Path, default=Path("retrain/gate_report.json"))
    pr.add_argument("--prepare-meta", type=Path, default=Path("retrain/prepare_meta.json"))
    args = parser.parse_args()

    if args.cmd == "prepare":
        prepare(args.out, args.force)
    elif args.cmd == "evaluate":
        evaluate(args.candidate, args.current, args.holdout, args.report)
    else:
        promote(args.candidate, args.report, args.prepare_meta)


if __name__ == "__main__":
    main()
