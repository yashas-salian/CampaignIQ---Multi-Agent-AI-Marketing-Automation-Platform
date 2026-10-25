import os
import re
import time

import requests

DEFAULT_INSTANCE = "https://mastodon.social"
MEDIA_READY_TRIES = 10  # an uploaded image may still be processing: poll ~1 s apart


def _instance() -> str:
    # `or`, not a get() default: GitHub Actions turns a missing secret into "", not "unset".
    return (os.environ.get("MASTODON_INSTANCE_URL") or DEFAULT_INSTANCE).rstrip("/")


def posting_enabled() -> bool:
    """Posting needs its own token with write:statuses + write:media; the
    search token (MASTODON_ACCESS_TOKEN) stays read-only."""
    return bool(os.environ.get("MASTODON_POST_TOKEN"))


def _post_headers() -> dict:
    return {"Authorization": f"Bearer {os.environ['MASTODON_POST_TOKEN']}"}


def search_mastodon(keyword: str, *, limit: int = 25) -> dict:
    headers = {}
    token = os.environ.get("MASTODON_ACCESS_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(
        f"{_instance()}/api/v2/search",
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
        "texts": [re.sub(r"<[^>]+>", " ", s.get("content") or "")[:280].strip() for s in statuses[:20] if s.get("content")],
    }


def _upload_image(image_bytes: bytes, image_alt: str) -> str:
    headers = _post_headers()
    response = requests.post(
        f"{_instance()}/api/v2/media",
        headers=headers,
        files={"file": ("ad.jpg", image_bytes, "image/jpeg")},
        data={"description": image_alt[:1500]} if image_alt else None,
        timeout=60,
    )
    response.raise_for_status()
    media = response.json()
    # 202 = still processing: attaching it now would fail, so wait until it has a URL.
    for _ in range(MEDIA_READY_TRIES):
        if media.get("url"):
            break
        time.sleep(1)
        check = requests.get(f"{_instance()}/api/v1/media/{media['id']}", headers=headers, timeout=30)
        check.raise_for_status()
        media = check.json()
    return media["id"]


def post_to_mastodon(text: str, image_bytes: bytes | None = None, image_alt: str = "", *, idempotency_key: str | None = None) -> str:
    """Posts a public status and returns its web URL (e.g. https://mastodon.social/@me/1234)."""
    headers = _post_headers()
    if idempotency_key:
        # Mastodon drops a repeat of the same key for an hour: a retried request can't post twice.
        headers["Idempotency-Key"] = idempotency_key
    body: dict = {"status": text, "visibility": "public"}
    if image_bytes:
        body["media_ids[]"] = [_upload_image(image_bytes, image_alt)]
    response = requests.post(f"{_instance()}/api/v1/statuses", headers=headers, data=body, timeout=30)
    response.raise_for_status()
    return response.json()["url"]


def status_id(post_url: str) -> str:
    return post_url.rstrip("/").rsplit("/", 1)[-1]


def get_mastodon_metrics(post_url: str) -> dict:
    # Public statuses can be read without a token; the post token is sent when present.
    headers = _post_headers() if posting_enabled() else {}
    response = requests.get(f"{_instance()}/api/v1/statuses/{status_id(post_url)}", headers=headers, timeout=30)
    response.raise_for_status()
    status = response.json()
    # Same names as Bluesky's, so the metrics page labels them alike (favourite = like, boost = repost).
    return {
        "likes": status.get("favourites_count", 0),
        "reposts": status.get("reblogs_count", 0),
        "replies": status.get("replies_count", 0),
    }
