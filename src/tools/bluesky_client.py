import os

from atproto import Client, client_utils


def _client() -> Client:
    client = Client()
    client.login(os.environ["BLUESKY_HANDLE"], os.environ["BLUESKY_APP_PASSWORD"])
    return client


def post_to_bluesky(text: str, image_bytes: bytes | None = None, image_alt: str = "") -> str:
    client = _client()
    text_builder = client_utils.TextBuilder().text(text)
    if image_bytes:
        post = client.send_image(text=text_builder, image=image_bytes, image_alt=image_alt)
    else:
        post = client.send_post(text_builder)
    return post.uri


def find_own_post(text: str, *, within_hours: int = 48) -> str | None:
    """The URI of our own post with exactly this text from the last
    `within_hours`, or None. Bluesky has no idempotency key, so a retry after
    a timed-out send checks here first (src/capabilities/delivery.py)."""
    from datetime import datetime, timedelta, timezone

    client = _client()
    feed = client.app.bsky.feed.get_author_feed({"actor": client.me.did, "limit": 30, "filter": "posts_no_replies"})
    since = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    for item in feed.feed:
        record = item.post.record
        created = datetime.fromisoformat(str(record.created_at).replace("Z", "+00:00"))
        if record.text == text and created >= since:
            return item.post.uri
    return None


def get_bluesky_metrics(post_uri: str) -> dict:
    client = _client()
    thread = client.get_post_thread(uri=post_uri)
    post = thread.thread.post
    return {
        "likes": post.like_count or 0,
        "reposts": post.repost_count or 0,
        "replies": post.reply_count or 0,
    }


def search_bluesky(keyword: str, *, limit: int = 25) -> dict:
    client = _client()
    response = client.app.bsky.feed.search_posts({"q": keyword, "limit": limit, "sort": "top"})
    posts = response.posts
    if not posts:
        return {"keyword": keyword, "result_count": 0, "avg_score": 0.0, "avg_comments": 0.0}
    return {
        "keyword": keyword,
        "result_count": len(posts),
        "avg_score": sum((p.like_count or 0) + (p.repost_count or 0) for p in posts) / len(posts),
        "avg_comments": sum(p.reply_count or 0 for p in posts) / len(posts),
    }
