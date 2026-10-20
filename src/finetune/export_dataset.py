"""Export real campaigns as extra training rows for the M7 classifier.

Pooling across users is acceptable here (DESIGN.md: the fine-tuning export is
the one place cross-user aggregation is fine) because it never flows back into
another user's live session. It still contains users' own words, so it is
written ONLY to a git-ignored file and carries no user ids or other fields.

The label is the domain each campaign actually ran with, i.e. what production
decided at the time. Ideas that are near-copies of the golden eval set are
dropped so evaluation stays clean.

Usage: .venv/Scripts/python.exe -m src.finetune.export_dataset
"""
import json

from dotenv import load_dotenv

from src.capabilities.idea_intake import DOMAIN_CATEGORIES
from src.db.supabase_client import get_client
from src.finetune.generate_dataset import DATA_DIR, GOLDEN, GOLDEN_LEAK_COSINE

OUT = DATA_DIR / "real_campaigns.jsonl"  # git-ignored (see .gitignore)


def main() -> None:
    load_dotenv()
    rows = get_client().table("campaigns").select("idea,domain_category").execute().data
    seen, real = set(), []
    for r in rows:
        idea = (r.get("idea") or "").strip()
        if idea and r.get("domain_category") in DOMAIN_CATEGORIES and idea.casefold() not in seen:
            seen.add(idea.casefold())
            real.append({"idea": idea, "label": r["domain_category"], "source": "real"})

    if real:
        from src.tools.memory import embed_texts

        golden = [json.loads(line)["idea"] for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
        leak = (embed_texts([r["idea"] for r in real]) @ embed_texts(golden).T).max(axis=1) >= GOLDEN_LEAK_COSINE
        real = [r for r, is_leak in zip(real, leak) if not is_leak]

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in real), encoding="utf-8")
    print(f"exported {len(real)} real campaigns -> {OUT} (git-ignored)")


if __name__ == "__main__":
    main()
