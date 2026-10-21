"""Prompt registry: every LLM prompt in one place, with an id and a version.

    from src.prompts import PROMPTS
    prompt, system = PROMPTS["creative.generate"].render(idea=..., ...)

* Templates use str.format fields; callers pass already-fenced/escaped values
  (see src.security.prompt_guard), the registry doesn't fence anything itself.
* Every system prompt gets the untrusted-data rule (prompt_guard.guarded).
* render() also marks the prompt as "current", so the LLM gateway records
  prompt id + version with each call (llm_usage, Langfuse): a quality change
  can be traced to the prompt change that caused it.
* Versions are locked to content: tests/unit/test_prompts.py fails when a
  template changes without a version bump (fingerprints.json), so every prompt
  change is deliberate and shows up in review and in the CHANGELOG.
"""
import hashlib
from contextvars import ContextVar
from dataclasses import dataclass

from src.security.prompt_guard import guarded

current_prompt: ContextVar[str | None] = ContextVar("current_prompt", default=None)


@dataclass(frozen=True)
class Prompt:
    id: str
    version: str
    system: str
    template: str
    guard: bool = True  # add the untrusted-data rule to the system prompt

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.system}\x00{self.template}\x00{self.guard}".encode()).hexdigest()[:16]

    def render(self, **fields) -> tuple[str, str]:
        current_prompt.set(self.ref)
        return self.template.format(**fields), guarded(self.system) if self.guard else self.system


from src.prompts.catalog import PROMPTS  # noqa: E402

__all__ = ["PROMPTS", "Prompt", "current_prompt"]
