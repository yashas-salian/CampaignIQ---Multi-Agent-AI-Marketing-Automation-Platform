from pytrends.request import TrendReq


def get_trend_interest(keyword: str) -> dict:
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], timeframe="today 3-m")
    df = pytrends.interest_over_time()

    if df.empty:
        return {"keyword": keyword, "mean_interest": 0, "latest_interest": 0, "trending_up": False}

    series = df[keyword]
    mean_interest = float(series.mean())
    latest_interest = float(series.iloc[-1])
    earlier_mean = float(series.iloc[: max(len(series) // 2, 1)].mean())
    return {
        "keyword": keyword,
        "mean_interest": mean_interest,
        "latest_interest": latest_interest,
        "trending_up": latest_interest > earlier_mean,
    }
