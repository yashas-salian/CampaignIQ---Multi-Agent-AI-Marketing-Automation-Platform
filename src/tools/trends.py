from pytrends.exceptions import TooManyRequestsError
from pytrends.request import TrendReq
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


@retry(
    retry=retry_if_exception_type(TooManyRequestsError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=3, min=3, max=15),
    reraise=True,
)
def _fetch_interest_over_time(keyword: str):
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], timeframe="today 3-m")
    return pytrends.interest_over_time()


def get_trend_interest(keyword: str) -> dict:
    try:
        df = _fetch_interest_over_time(keyword)
    except TooManyRequestsError:
        # Google Trends' unofficial API rate-limits hard under repeated use
        # (e.g. the eval harness running many ideas back-to-back). Degrade to
        # a neutral signal rather than crashing the whole run, but flag it so
        # callers (rationale writer, eval report) know this isn't a genuine
        # zero-interest measurement.
        return {"keyword": keyword, "mean_interest": 0, "latest_interest": 0, "trending_up": False, "rate_limited": True}

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
