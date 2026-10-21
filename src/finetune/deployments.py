"""Model registry for the fine-tuned domain classifier (M7).

Every promoted model is a commit in the private Hugging Face repo
(DOMAIN_MODEL_HF_REPO); `model_deployments` says which commit serves traffic
and how a candidate is being tried (see *_model_deployments.sql).

    python -m src.finetune.deployments list                 promoted versions + their metrics
    python -m src.finetune.deployments status               what's deployed now (+ shadow agreement)
    python -m src.finetune.deployments activate <rev>       serve this revision
    python -m src.finetune.deployments rollback             back to the previous active revision
    python -m src.finetune.deployments shadow <rev>         run <rev> silently next to the active model
    python -m src.finetune.deployments canary <rev> <pct>   send pct% of ideas to <rev>
    python -m src.finetune.deployments off                  stop shadow/canary
"""
import json
import logging
import os
import sys
from functools import lru_cache

logger = logging.getLogger("finetune.deployments")

MODEL = "domain-classifier"


@lru_cache(maxsize=1)
def current() -> dict:
    """The deployment row, or {} (latest commit, no candidate) when unavailable."""
    try:
        from src.db.supabase_client import get_client

        row = get_client().table("model_deployments").select("*").eq("model", MODEL).maybe_single().execute()
        return (row.data if row else None) or {}
    except Exception as exc:
        logger.info("model deployment lookup failed (%s): serving the latest model", exc)
        return {}


def _update(**fields) -> dict:
    from src.db.supabase_client import get_client

    fields["updated_by"] = os.environ.get("GITHUB_ACTOR") or os.environ.get("USERNAME") or os.environ.get("USER") or "cli"
    get_client().table("model_deployments").update(fields).eq("model", MODEL).execute()
    current.cache_clear()
    return current()


def record_promotion(revision: str) -> None:
    """Called by the weekly retrain after it uploads a model that passed the gate."""
    previous = current().get("active_revision")
    _update(active_revision=revision, previous_revision=previous, candidate_revision=None, mode="off", canary_percent=0)


def history() -> list[dict]:
    from huggingface_hub import HfApi, hf_hub_download

    repo, token = os.environ["DOMAIN_MODEL_HF_REPO"], os.environ.get("HF_TOKEN") or None
    out = []
    for commit in HfApi(token=token).list_repo_commits(repo):
        entry = {"revision": commit.commit_id, "date": commit.created_at.isoformat(), "title": commit.title}
        try:
            meta = json.loads(open(hf_hub_download(repo, "training_meta.json", revision=commit.commit_id, token=token)).read())
            entry["metrics"] = meta.get("metrics")
        except Exception:
            pass
        out.append(entry)
    return out


def shadow_agreement(candidate: str) -> dict:
    from src.db.supabase_client import get_client

    rows = (
        get_client().table("model_shadow_log").select("agreed").eq("candidate_revision", candidate).limit(5000).execute().data
    )
    agreed = sum(1 for r in rows if r["agreed"])
    return {"compared": len(rows), "agreement": round(agreed / len(rows), 3) if rows else None}


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    args = sys.argv[1:] or ["status"]
    cmd = args[0]
    if cmd == "list":
        active = current().get("active_revision")
        for h in history():
            mark = "*" if h["revision"] == active else " "
            print(f"{mark} {h['revision'][:12]}  {h['date'][:16]}  {h['title'][:40]:<40}  {h.get('metrics') or ''}")
    elif cmd == "status":
        row = current()
        print(json.dumps(row, indent=2, default=str))
        if row.get("candidate_revision"):
            print("shadow agreement:", shadow_agreement(row["candidate_revision"]))
    elif cmd == "activate":
        row = current()
        print(_update(active_revision=args[1], previous_revision=row.get("active_revision"), mode="off", canary_percent=0))
    elif cmd == "rollback":
        row = current()
        if not row.get("previous_revision"):
            sys.exit("no previous revision recorded")
        print(_update(active_revision=row["previous_revision"], previous_revision=row.get("active_revision"),
                      mode="off", canary_percent=0))
    elif cmd == "shadow":
        print(_update(candidate_revision=args[1], mode="shadow", canary_percent=0))
    elif cmd == "canary":
        pct = int(args[2])
        if not 0 <= pct <= 100:
            sys.exit("percent must be 0-100")
        print(_update(candidate_revision=args[1], mode="canary", canary_percent=pct))
    elif cmd == "off":
        print(_update(candidate_revision=None, mode="off", canary_percent=0))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
