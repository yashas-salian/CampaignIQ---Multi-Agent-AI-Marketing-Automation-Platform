"""Run a GGUF classifier (base or fine-tuned) on CPU with llama.cpp.

Shared by evaluate_finetune.py and the production provider. llama-cpp-python is
imported lazily so the rest of the app never depends on it being installed.
"""
import os
from functools import lru_cache

from src.finetune.prompt import build_messages, parse_label


@lru_cache(maxsize=2)
def _load(model_path: str):
    from llama_cpp import Llama

    return Llama(
        model_path=model_path,
        n_ctx=512,
        n_threads=max(1, (os.cpu_count() or 2) - 1),
        verbose=False,
    )


def classify(idea: str, model_path: str) -> tuple[str | None, str]:
    """(parsed label or None, raw reply). Greedy decoding, a handful of tokens."""
    reply = _load(model_path).create_chat_completion(
        messages=build_messages(idea),
        max_tokens=8,
        temperature=0.0,
    )
    raw = reply["choices"][0]["message"]["content"] or ""
    return parse_label(raw), raw
