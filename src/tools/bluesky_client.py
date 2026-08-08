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


def get_bluesky_metrics(post_uri: str) -> dict:
    client = _client()
    thread = client.get_post_thread(uri=post_uri)
    post = thread.thread.post
    return {
        "likes": post.like_count or 0,
        "reposts": post.repost_count or 0,
        "replies": post.reply_count or 0,
    }
