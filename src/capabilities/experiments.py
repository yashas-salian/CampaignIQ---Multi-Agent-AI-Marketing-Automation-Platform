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


# Bayesian read-out, shown as "92% chance B beats A". The test is called (and the
# split stopped) once either side is this likely to be better, with enough people.
DECISION_PROBABILITY = 0.95
MIN_RECIPIENTS_PER_VARIANT = 10


def bayesian_ab(clicks_a: int, n_a: int, clicks_b: int, n_b: int, *, draws: int = 20000, seed: int = 7) -> dict:
    """Beta(1, 1) priors on each click rate, compared by sampling the posteriors.

    Returns P(B beats A), B's expected relative lift over A, a 95% interval on
    the rate difference (B - A), and `decided` ("a"/"b") once the evidence is
    strong enough to stop splitting. Fixed seed: the same counts always give
    the same read-out."""
    import numpy as np

    result = {"prob_b_beats_a": None, "expected_lift": None, "interval": None, "decided": None,
              "threshold": DECISION_PROBABILITY, "min_recipients": MIN_RECIPIENTS_PER_VARIANT}
    if not n_a or not n_b:
        return result
    # click_log counts clicks, not people: never let clicks exceed recipients.
    clicks_a, clicks_b = min(clicks_a, n_a), min(clicks_b, n_b)
    rng = np.random.default_rng(seed)
    a = rng.beta(1 + clicks_a, 1 + n_a - clicks_a, draws)
    b = rng.beta(1 + clicks_b, 1 + n_b - clicks_b, draws)
    prob = float((b > a).mean())
    low, high = np.percentile(b - a, [2.5, 97.5])
    result.update(
        prob_b_beats_a=round(prob, 4),
        expected_lift=round(float(np.mean((b - a) / a)), 4),
        interval=[round(float(low), 4), round(float(high), 4)],
    )
    if min(n_a, n_b) >= MIN_RECIPIENTS_PER_VARIANT:
        if prob >= DECISION_PROBABILITY:
            result["decided"] = "b"
        elif prob <= 1 - DECISION_PROBABILITY:
            result["decided"] = "a"
    return result
