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
"""
import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("providers.local_domain_classifier")

DEFAULT_FILE = "marketingos-domain-q4_k_m.gguf"
LOCAL_DIR = Path(__file__).resolve().parents[2] / "finetune" / "models"


def enabled() -> bool:
    return os.environ.get("DOMAIN_CLASSIFIER", "local").strip().lower() != "llm"


@lru_cache(maxsize=1)
def _model_path() -> str | None:
    explicit = os.environ.get("DOMAIN_MODEL_PATH")
    if explicit and Path(explicit).is_file():
        return explicit
    local = LOCAL_DIR / DEFAULT_FILE
    if local.is_file():
        return str(local)
    repo = os.environ.get("DOMAIN_MODEL_HF_REPO")
    if not repo:
        return None
    try:
        from huggingface_hub import hf_hub_download

        return hf_hub_download(
            repo_id=repo,
            filename=os.environ.get("DOMAIN_MODEL_HF_FILE", DEFAULT_FILE),
            token=os.environ.get("HF_TOKEN") or None,
        )
    except Exception as exc:  # network, auth, missing file: degrade, don't crash
        logger.warning("domain model download from %s failed: %s", repo, exc)
        return None


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
    try:
        from src.finetune.local_classifier import classify

        label, raw = classify(idea, _model_path())
    except Exception as exc:
        logger.warning("domain classifier failed on one idea (%s) -> using the LLM", exc)
        return None
    if label is None:
        logger.info("domain classifier returned no valid category (%r) -> using the LLM", raw[:40])
    return label
