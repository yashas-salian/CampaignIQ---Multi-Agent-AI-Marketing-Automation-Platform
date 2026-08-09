import os

import requests

DEFAULT_INSTANCE = "https://mastodon.social"


def search_mastodon(keyword: str, *, limit: int = 25) -> dict:
    instance = os.environ.get("MASTODON_INSTANCE_URL", DEFAULT_INSTANCE).rstrip("/")
    headers = {}
    token = os.environ.get("MASTODON_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        f"{instance}/api/v2/search",
        params={"q": keyword, "type": "statuses", "limit": min(limit, 40)},
        headers=headers,
        timeout=30,
    )
    response.raise_for_status()
    statuses = response.json().get("statuses", [])

    if not statuses:
        return {"keyword": keyword, "result_count": 0, "avg_score": 0.0, "avg_comments": 0.0}
    return {
        "keyword": keyword,
        "result_count": len(statuses),
        "avg_score": sum(s["favourites_count"] + s["reblogs_count"] for s in statuses) / len(statuses),
        "avg_comments": sum(s["replies_count"] for s in statuses) / len(statuses),
    }
