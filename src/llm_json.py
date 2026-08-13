import json
from typing import Any

from src.constants import MAX_REGENERATION_ATTEMPTS


def _clean_payload(response: str) -> str:
    payload = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    # JSON only requires escaping double quotes; free-tier models nonetheless
    # sometimes escape apostrophes in contractions ("campaign\'s"), which is
    # invalid JSON syntax.
    return payload.replace("\\'", "'")


def parse_llm_json(response: str) -> Any:
    """Parse a JSON object/array out of an LLM's text response, tolerating
    markdown code fences and literal control characters inside strings."""
    return json.loads(_clean_payload(response), strict=False)


def generate_json(llm, prompt: str, *, system: str) -> Any:
    """Call llm.generate() and parse its JSON output, retrying the call itself
    (not just the parse) on failure. Free-tier models occasionally truncate a
    string mid-value (e.g. a missing closing quote before the next key) --
    no post-processing can reliably repair that, so resampling is the
    practical fix.
    """
    last_error: json.JSONDecodeError | None = None
    for _ in range(MAX_REGENERATION_ATTEMPTS):
        response = llm.generate(prompt, system=system)
        try:
            return parse_llm_json(response)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise last_error
