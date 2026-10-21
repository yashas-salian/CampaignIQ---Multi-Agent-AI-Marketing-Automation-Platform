"""Prompt registry tools.

    python -m src.prompts                        list prompts with version + fingerprint
    python -m src.prompts --update-fingerprints  record the current content (after bumping versions)
"""
import json
import sys
from pathlib import Path

from src.prompts import PROMPTS

FINGERPRINTS = Path(__file__).with_name("fingerprints.json")


def main() -> None:
    current = {p.id: {"version": p.version, "fingerprint": p.fingerprint} for p in PROMPTS.values()}
    if "--update-fingerprints" in sys.argv:
        recorded = json.loads(FINGERPRINTS.read_text(encoding="utf-8")) if FINGERPRINTS.exists() else {}
        for pid, now in current.items():
            before = recorded.get(pid)
            if before and before["fingerprint"] != now["fingerprint"] and before["version"] == now["version"]:
                sys.exit(f"{pid}: the text changed but the version is still {now['version']}; bump it first")
        FINGERPRINTS.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"recorded {len(current)} prompts in {FINGERPRINTS.name}")
        return
    for pid, now in sorted(current.items()):
        print(f"{pid:<24} {now['version']:<8} {now['fingerprint']}")


if __name__ == "__main__":
    main()
