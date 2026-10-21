"""A/B test statistics for email variants.

Recipients are split deterministically into halves (the same list always splits
the same way, so a resumed run never re-shuffles who got what), and click rates
are compared with a two-sided two-proportion z-test.
"""
import math


def split_recipients(recipients: list[str]) -> tuple[list[str], list[str]]:
    """Alternate over the sorted, de-duplicated list: A gets 1st, 3rd, ..."""
    ordered = sorted(dict.fromkeys(r.strip().lower() for r in recipients if r and r.strip()))
    return ordered[0::2], ordered[1::2]


def _normal_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def two_proportion_test(clicks_a: int, n_a: int, clicks_b: int, n_b: int, *, alpha: float = 0.05) -> dict:
    """Compare click rates. `winner` is set only when the difference is significant."""
    rate_a = clicks_a / n_a if n_a else 0.0
    rate_b = clicks_b / n_b if n_b else 0.0
    result = {
        "rate_a": round(rate_a, 4),
        "rate_b": round(rate_b, 4),
        "lift": round((rate_b - rate_a) / rate_a, 4) if rate_a else None,
        "p_value": None,
        "significant": False,
        "winner": None,
    }
    if not n_a or not n_b:
        return result
    pooled = (clicks_a + clicks_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    if se == 0:
        result["p_value"] = 1.0
        return result
    z = (rate_b - rate_a) / se
    p = 2 * (1 - _normal_cdf(abs(z)))
    result["p_value"] = round(p, 4)
    result["significant"] = p < alpha
    if result["significant"]:
        result["winner"] = "b" if rate_b > rate_a else "a"
    return result
