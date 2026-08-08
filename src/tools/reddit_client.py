import os

import praw


def _client() -> praw.Reddit:
    return praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        username=os.environ["REDDIT_USERNAME"],
        password=os.environ["REDDIT_PASSWORD"],
        user_agent=os.environ.get("REDDIT_USER_AGENT", "ad-campaign-agent/0.1 by u/unknown"),
    )


def search_reddit(keyword: str, *, limit: int = 25) -> dict:
    reddit = _client()
    posts = list(reddit.subreddit("all").search(keyword, limit=limit))
    if not posts:
        return {"keyword": keyword, "result_count": 0, "avg_score": 0.0, "avg_comments": 0.0}
    return {
        "keyword": keyword,
        "result_count": len(posts),
        "avg_score": sum(p.score for p in posts) / len(posts),
        "avg_comments": sum(p.num_comments for p in posts) / len(posts),
    }


def post_to_reddit(subreddit: str, title: str, body: str) -> str:
    reddit = _client()
    submission = reddit.subreddit(subreddit).submit(title=title, selftext=body)
    return f"https://reddit.com{submission.permalink}"


def get_reddit_metrics(post_url: str) -> dict:
    reddit = _client()
    submission = reddit.submission(url=post_url)
    submission.comment_sort = "top"
    return {"score": submission.score, "num_comments": submission.num_comments, "upvote_ratio": submission.upvote_ratio}
