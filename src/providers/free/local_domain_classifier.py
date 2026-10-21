"""M7: the fine-tuned domain classifier, run locally on CPU via llama.cpp.

Free-tier campaigns use it instead of a Groq call to pick the product category
(the bandit's domain context). It must never break a run: if it's disabled,
the model file can't be found or downloaded, llama-cpp-python isn't installed,
or the reply isn't a valid category, classify_domain() returns None and the
caller falls back to the LLM.

Where the model comes from, first match wins:
  1. DOMAIN_MODEL_PATH                    -- an explicit file path
  2. src/finetune/models/<DEFAULT_FILE>   -- local dev (git-ignored)
  3. DOMAIN_MODEL_HF_REPO (+ HF_TOKEN)    -- a (private) Hugging Face model repo;
                                             cached by huggingface_hub, and by
                                             actions/cache in the workflows
Set DOMAIN_CLASSIFIER=llm to switch it off entirely.

Which Hugging Face revision serves traffic, and whether a candidate runs in
shadow or canary mode, comes from the model registry (src/finetune/deployments.py).
"""
import hashlib
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("providers.local_domain_classifier")

DEFAULT_FILE = "marketingos-domain-q4_k_m.gguf"
LOCAL_DIR = Path(__file__).resolve().parents[2] / "finetune" / "models"


def enabled() -> bool:
    return os.environ.get("DOMAIN_CLASSIFIER", "local").strip().lower() != "llm"


def _download(revision: str | None) -> str | None:
    repo = os.environ.get("DOMAIN_MODEL_HF_REPO")
    if not repo:
        return None
    try:
        from huggingface_hub import hf_hub_download

        return hf_hub_download(
            repo_id=repo,
            filename=os.environ.get("DOMAIN_MODEL_HF_FILE", DEFAULT_FILE),
            revision=revision,
            token=os.environ.get("HF_TOKEN") or None,
        )
    except Exception as exc:  # network, auth, missing file: degrade, don't crash
        logger.warning("domain model download from %s@%s failed: %s", repo, revision or "latest", exc)
        return None


def _deployment() -> dict:
    from src.finetune.deployments import current

    return current() if os.environ.get("DOMAIN_MODEL_HF_REPO") else {}


@lru_cache(maxsize=1)
def _model_path() -> str | None:
    explicit = os.environ.get("DOMAIN_MODEL_PATH")
    if explicit and Path(explicit).is_file():
        return explicit
    local = LOCAL_DIR / DEFAULT_FILE
    if local.is_file():
        return str(local)
    return _download(_deployment().get("active_revision"))


@lru_cache(maxsize=1)
def _candidate_path() -> str | None:
    deployment = _deployment()
    if deployment.get("mode") in ("shadow", "canary") and deployment.get("candidate_revision"):
        return _download(deployment["candidate_revision"])
    return None


def _idea_bucket(idea: str) -> int:
    """Stable 0-99 bucket per idea, so a canary percentage is deterministic."""
    return int(hashlib.sha256(idea.strip().lower().encode()).hexdigest()[:8], 16) % 100


def _log_shadow(idea: str, active: str | None, candidate: str | None) -> None:
    deployment = _deployment()
    try:
        from src.db.supabase_client import get_client

        get_client().table("model_shadow_log").insert({
            "model": "domain-classifier",
            "active_revision": deployment.get("active_revision"),
            "candidate_revision": deployment["candidate_revision"],
            "active_label": active,
            "candidate_label": candidate,
            "idea_hash": hashlib.sha256(idea.strip().lower().encode()).hexdigest()[:16],
        }).execute()
    except Exception as exc:
        logger.debug("shadow log not written: %s", exc)


@lru_cache(maxsize=1)
def available() -> bool:
    """True once the model file is present and llama.cpp can load it."""
    if not enabled():
        return False
    path = _model_path()
    if not path:
        logger.info("domain classifier: no local model found -> using the LLM")
        return False
    try:
        from src.finetune.local_classifier import _load

        _load(path)
    except Exception as exc:  # llama-cpp-python missing, corrupt file, out of memory
        logger.warning("domain classifier: local model unavailable (%s) -> using the LLM", exc)
        return False
    logger.info("domain classifier: fine-tuned local model (%s)", Path(path).name)
    return True


def classify_domain(idea: str) -> str | None:
    """Category from the fine-tuned model, or None (caller then asks the LLM)."""
    if not available():
        return None
    from src.finetune.local_classifier import classify

    deployment = _deployment()
    candidate = _candidate_path()
    use_candidate = (
        candidate is not None
        and deployment.get("mode") == "canary"
        and _idea_bucket(idea) < int(deployment.get("canary_percent") or 0)
    )
    try:
        label, raw = classify(idea, candidate if use_candidate else _model_path())
    except Exception as exc:
        logger.warning("domain classifier failed on one idea (%s) -> using the LLM", exc)
        return None
    if candidate is not None and deployment.get("mode") == "shadow":
        try:
            shadow_label, _ = classify(idea, candidate)
        except Exception:
            shadow_label = None
        _log_shadow(idea, label, shadow_label)
    if label is None:
        logger.info("domain classifier returned no valid category (%r) -> using the LLM", raw[:40])
    return label
