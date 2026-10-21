"""Build the synthetic, teacher-labelled dataset for the M7 domain classifier.

Pipeline (each stage caches to disk, so a run interrupted by free-tier rate
limits resumes where it stopped):
  1. generate  -- the teacher LLM writes varied campaign ideas per domain/angle
  2. label     -- every idea goes through the real normalize_idea() path, so the
                  student learns exactly what production does (not the domain the
                  idea was generated for)
  3. filter    -- drop near-duplicates, and anything too close to the 18-idea
                  golden set (src/eval) so evaluation isn't contaminated
  4. split     -- stratified train / val / test

Usage: .venv/Scripts/python.exe -m src.finetune.generate_dataset
"""
import json
import random
import time
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from src.capabilities.idea_intake import DOMAIN_CATEGORIES, normalize_idea
from src.llm_json import generate_json
from src.providers.registry import get_llm

DATA_DIR = Path(__file__).parent / "data"
IDEAS_CACHE = DATA_DIR / "ideas_cache.jsonl"
LABELS_CACHE = DATA_DIR / "labels_cache.jsonl"
GOLDEN = Path(__file__).parent.parent / "eval" / "golden_set.jsonl"

SEED = 7
IDEAS_PER_ANGLE = 7
BORDERLINE_IDEAS = 5
DUPLICATE_COSINE = 0.90  # near-identical ideas within the dataset
GOLDEN_LEAK_COSINE = 0.80  # too close to an eval idea -> excluded
TEST_PER_LABEL = 10
VAL_PER_LABEL = 5
CALL_PAUSE_S = 1.2

# Languages the app supports for campaigns (src/languages.py), used so the
# student also sees ideas typed in non-English, as real users do.
FOREIGN_LANGUAGES = ["Spanish", "Hindi", "French", "Portuguese", "German", "Japanese"]

ANGLES = [
    "a consumer (B2C) product or app",
    "a service sold to other businesses (B2B)",
    "a local or small independent business",
    "a premium or luxury offering",
    "a budget-friendly offering for students or young people",
    "written entirely in {language} (not English)",
]


def _with_backoff(fn, *args, **kwargs):
    """Free-tier calls can be rate-limited; wait and retry instead of failing the run."""
    delay = 20
    for attempt in range(6):
        try:
            result = fn(*args, **kwargs)
            time.sleep(CALL_PAUSE_S)
            return result
        except Exception as exc:  # groq.RateLimitError, transient network, bad JSON
            if attempt == 5:
                raise
            print(f"  ! {type(exc).__name__}: {str(exc)[:90]} -> retrying in {delay}s", flush=True)
            time.sleep(delay)
            delay = min(delay * 2, 180)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _append_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


# ---------------------------------------------------------------- 1. generate
def _generation_jobs() -> list[dict]:
    jobs = []
    for d_i, domain in enumerate(DOMAIN_CATEGORIES):
        for angle in ANGLES:
            language = FOREIGN_LANGUAGES[d_i % len(FOREIGN_LANGUAGES)]
            jobs.append({"domain": domain, "angle": angle.format(language=language), "n": IDEAS_PER_ANGLE})
        jobs.append({"domain": domain, "angle": "borderline: could plausibly also fit another category", "n": BORDERLINE_IDEAS})
    return jobs


def generate() -> list[dict]:
    llm = get_llm(None)
    done = {(r["domain"], r["angle"]) for r in _read_jsonl(IDEAS_CACHE)}
    jobs = [j for j in _generation_jobs() if (j["domain"], j["angle"]) not in done]
    print(f"[generate] {len(done)} batches cached, {len(jobs)} to go", flush=True)
    for i, job in enumerate(jobs, 1):
        prompt = (
            f'Write {job["n"]} distinct one-sentence ad-campaign ideas for the "{job["domain"]}" product category, '
            f'each one {job["angle"]}. Make each specific: what the product is and who it is for, in the style '
            '"A subscription box that delivers ... to ...". Vary the products, audiences and price points; do '
            'not number them. Respond with ONLY a JSON object: {"ideas": ["...", "..."]}.'
        )
        parsed = _with_backoff(
            generate_json, llm, prompt, system="You write realistic, varied startup and small-business campaign ideas. Output only valid JSON."
        )
        ideas = [str(x).strip() for x in parsed.get("ideas", []) if str(x).strip()][: job["n"]]
        # Mark the batch done even if it came back short, so reruns don't loop on it.
        _append_jsonl(IDEAS_CACHE, [{"domain": job["domain"], "angle": job["angle"], "idea": idea} for idea in ideas] or
                      [{"domain": job["domain"], "angle": job["angle"], "idea": None}])
        print(f"  [{i}/{len(jobs)}] {job['domain']:<22} {len(ideas)} ideas | {job['angle'][:48]}", flush=True)
    return [r for r in _read_jsonl(IDEAS_CACHE) if r["idea"]]


# ------------------------------------------------------------------- 2. label
def label(ideas: list[dict]) -> dict[str, str]:
    labels = {r["idea"]: r["label"] for r in _read_jsonl(LABELS_CACHE)}
    todo = [r["idea"] for r in ideas if r["idea"] not in labels]
    print(f"[label] {len(labels)} cached, {len(todo)} to go", flush=True)
    for i, idea in enumerate(todo, 1):
        try:
            result = _with_backoff(normalize_idea, idea, use_local=False)  # teacher, never the student
        except Exception as exc:
            print(f"  ! giving up on one idea: {str(exc)[:80]}", flush=True)
            continue
        labels[idea] = result.domain_category
        _append_jsonl(LABELS_CACHE, [{"idea": idea, "label": result.domain_category}])
        if i % 25 == 0 or i == len(todo):
            print(f"  labelled {i}/{len(todo)}", flush=True)
    return labels


# ------------------------------------------------------------------ 3. filter
def filter_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    from src.tools.memory import embed_texts

    golden = [json.loads(line)["idea"] for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    vecs = embed_texts([r["idea"] for r in rows])
    golden_vecs = embed_texts(golden)

    leak = (vecs @ golden_vecs.T).max(axis=1) >= GOLDEN_LEAK_COSINE
    kept, kept_vecs, dupes = [], [], 0
    for row, vec, is_leak in zip(rows, vecs, leak):
        if is_leak:
            continue
        if kept_vecs and max(float(vec @ k) for k in kept_vecs) >= DUPLICATE_COSINE:
            dupes += 1
            continue
        kept.append(row)
        kept_vecs.append(vec)
    return kept, {"golden_leaks_removed": int(leak.sum()), "near_duplicates_removed": dupes}


# ------------------------------------------------------------------- 4. split
def split(rows: list[dict]) -> dict[str, list[dict]]:
    rng = random.Random(SEED)
    by_label: dict[str, list[dict]] = {}
    for r in rows:
        by_label.setdefault(r["label"], []).append(r)
    out = {"train": [], "val": [], "test": []}
    for items in by_label.values():
        rng.shuffle(items)
        # Small classes still get a test example before they get training data.
        n_test = min(TEST_PER_LABEL, max(1, len(items) // 4))
        n_val = min(VAL_PER_LABEL, max(0, (len(items) - n_test) // 6))
        out["test"] += items[:n_test]
        out["val"] += items[n_test : n_test + n_val]
        out["train"] += items[n_test + n_val :]
    for part in out.values():
        rng.shuffle(part)
    return out


def main() -> None:
    load_dotenv()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ideas = generate()
    labels = label(ideas)

    seen, rows = set(), []
    for r in ideas:
        key = r["idea"].casefold()
        if r["idea"] in labels and key not in seen:
            seen.add(key)
            rows.append({
                "idea": r["idea"],
                "label": labels[r["idea"]],
                "generated_for": r["domain"],
                "angle": r["angle"],
                "source": "synthetic",
            })

    kept, removed = filter_rows(rows)
    parts = split(kept)
    for name, part in parts.items():
        _write_jsonl(DATA_DIR / f"{name}.jsonl", part)

    agree = sum(r["label"] == r["generated_for"] for r in kept)
    stats = {
        "generated": len(ideas),
        "labelled_unique": len(rows),
        **removed,
        "kept": len(kept),
        "teacher_agrees_with_generation_target": round(agree / max(1, len(kept)), 3),
        "split_sizes": {k: len(v) for k, v in parts.items()},
        "label_counts": {k: dict(sorted(Counter(r["label"] for r in v).items())) for k, v in parts.items()},
        "teacher_model": "groq openai/gpt-oss-120b (free tier, via normalize_idea)",
        "seed": SEED,
    }
    (DATA_DIR / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
