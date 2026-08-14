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
