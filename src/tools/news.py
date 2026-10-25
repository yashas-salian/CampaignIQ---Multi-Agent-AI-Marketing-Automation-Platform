import os

import requests

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def get_news_volume(keyword: str, *, page_size: int = 20, language: str = "en") -> dict:
    api_key = os.environ["NEWSAPI_KEY"]
    response = requests.get(
        NEWSAPI_URL,
        params={
            "q": keyword,
            "pageSize": page_size,
            "sortBy": "relevancy",
            "language": language,
            "apiKey": api_key,
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    articles = data.get("articles", [])
    return {
        "keyword": keyword,
        "total_results": data.get("totalResults", 0),
        "headlines": [a["title"] for a in articles if a.get("title")],
    }


def search_articles(query: str, *, language: str = "en", since: str | None = None, page_size: int = 30) -> list[dict]:
    """Articles with what's needed to trace them: title, description, url,
    outlet and publication time (competitor intelligence). Newest first."""
    api_key = os.environ["NEWSAPI_KEY"]
    params = {"q": query, "pageSize": page_size, "sortBy": "publishedAt", "language": language, "apiKey": api_key}
    if since:
        params["from"] = since
    response = requests.get(NEWSAPI_URL, params=params, timeout=30)
    response.raise_for_status()
    return [
        {
            "title": a.get("title") or "",
            "description": a.get("description") or "",
            "url": a.get("url"),
            "outlet": (a.get("source") or {}).get("name"),
            "published_at": a.get("publishedAt"),
        }
        for a in response.json().get("articles", [])
        if a.get("title") and a.get("url")
    ]
