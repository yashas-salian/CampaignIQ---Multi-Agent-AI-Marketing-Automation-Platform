import json
import os
from pathlib import Path

DEDUP_FILE = Path(os.environ.get("DEDUP_STORE_PATH", ".local_dedup_store.json"))


def _load() -> dict:
    if DEDUP_FILE.exists():
        return json.loads(DEDUP_FILE.read_text())
    return {}


def _save(data: dict) -> None:
    DEDUP_FILE.write_text(json.dumps(data, indent=2))


def _key(campaign_id: str, round_id: int, channel: str) -> str:
    return f"{campaign_id}:{round_id}:{channel}"


def already_sent(campaign_id: str, round_id: int, channel: str) -> bool:
    return _key(campaign_id, round_id, channel) in _load()


def mark_sent(campaign_id: str, round_id: int, channel: str, result: str) -> None:
    data = _load()
    data[_key(campaign_id, round_id, channel)] = result
    _save(data)
