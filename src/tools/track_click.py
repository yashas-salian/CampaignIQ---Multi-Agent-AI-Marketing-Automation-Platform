import os
from urllib.parse import quote


def wrap_tracked_url(url: str, *, campaign_id: str, round_id: int, channel: str = "email") -> str:
    base = os.environ["TRACK_CLICK_BASE_URL"].rstrip("/")
    return f"{base}?url={quote(url, safe='')}&campaign_id={campaign_id}&round_id={round_id}&channel={channel}"
