"""Proof-of-impact engine: did the campaign cause extra conversions?

Clicks and likes show activity, not value. This module runs a campaign's email
audience as a pre-registered randomized experiment and estimates what the
campaign *caused*, compared with a control group that got nothing.

Design (declared before the first send, locked once it starts; table
`experiments`, docs/PROOF_OF_IMPACT.md):
  - hypothesis, primary metric (qualified sign-ups, any conversion, or click-
    through for an A-vs-B test only: a control group can't click), the split,
    the attribution window and a fixed-horizon stopping rule (duration plus
    window; the minimum sample per group and the smallest lift worth acting on);
  - assignment unit: one email recipient. The arm is a stable hash of the
    experiment and the address, stored on first use: retries, resumed runs and
    later rounds never move anyone. Control recipients are simply not emailed.

Analysis (policy `impact-v1`, deterministic):
  - intention-to-treat: every assigned unit counts in its arm, whether or not
    the email arrived; a unit succeeds if it converted (or clicked) within the
    experiment's outcome window;
  - absolute lift with a Newcombe hybrid-score 95% interval (sound with zero
    conversions, small samples and unequal groups), P(treatment better) from
    Beta(1, 1) posteriors, and relative lift only when the control group has
    enough conversions for a stable baseline;
  - a sample-ratio-mismatch check (the assignment itself is checked before
    any effect is believed);
  - observed numbers, the causal estimate and attribution-based revenue are
    kept apart. Nothing here compares before with after.

Before the predeclared end the status is COLLECTING (interim numbers, no
verdict: no peeking). At the end: POSITIVE_IMPACT, NEGATIVE_IMPACT,
NO_MEANINGFUL_IMPACT or INCONCLUSIVE with a reason (INSUFFICIENT_DATA,
NO_OUTCOME_DATA, SAMPLE_RATIO_MISMATCH, INTERVAL_TOO_WIDE). A valid final
result feeds the bandit with an explicitly defined conversion reward.
"""
import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("capabilities.impact")

POLICY_VERSION = "impact-v1"
Z95 = 1.959963984540054
SRM_ALPHA = 0.001          # the usual threshold: a split this unlikely means the assignment broke
MIN_BASELINE_SUCCESSES = 10  # relative lift needs a control rate that isn't a handful of events
STALE_OUTCOME_HOURS = 72     # running, conversions had been arriving, then nothing for this long
CONVERSION_METRICS = ("qualified_signup_rate", "conversion_rate")
ARMS = ("control", "treatment", "treatment_b")


# --- Assignment -------------------------------------------------------------------------------

def normalise(address: str) -> str:
    return address.strip().lower()


def unit_hash(experiment_id: str, address: str) -> str:
    """The unit's identity in the experiment: the address itself isn't stored with the assignment."""
    return hashlib.sha256(f"{experiment_id}:{normalise(address)}".encode()).hexdigest()


def _uniform(experiment_id: str, uhash: str) -> float:
    return int(hashlib.sha256(f"arm:{experiment_id}:{uhash}".encode()).hexdigest()[:15], 16) / 16**15


def assign_arm(experiment_id: str, uhash: str, design: str, control_share: float) -> str:
    """Deterministic: the same experiment and unit always give the same arm."""
    u = _uniform(experiment_id, uhash)
    if design == "ab":
        return "treatment" if u < 0.5 else "treatment_b"
    if u < control_share:
        return "control"
    if design == "holdout_ab":
        return "treatment" if (u - control_share) / (1 - control_share) < 0.5 else "treatment_b"
    return "treatment"


def expected_shares(design: str, control_share: float) -> dict[str, float]:
    if design == "ab":
        return {"treatment": 0.5, "treatment_b": 0.5}
    if design == "holdout_ab":
        return {"control": control_share, "treatment": (1 - control_share) / 2, "treatment_b": (1 - control_share) / 2}
    return {"control": control_share, "treatment": 1 - control_share}


def comparison(design: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(treatment arms, baseline arms) of the primary comparison."""
    if design == "ab":
        return ("treatment_b",), ("treatment",)
    if design == "holdout_ab":
        return ("treatment", "treatment_b"), ("control",)
    return ("treatment",), ("control",)


# --- Statistics (pure) --------------------------------------------------------------------------

def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion (well-behaved at 0 and n)."""
    if n <= 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def newcombe_diff(k_t: int, n_t: int, k_c: int, n_c: int, z: float = Z95) -> tuple[float, float, float] | None:
    """Difference of proportions (treatment - control) with Newcombe's hybrid
    score interval (method 10): built from the two Wilson intervals, so it
    stays inside [-1, 1], handles zero events and unequal group sizes, and has
    close to nominal coverage in small samples (Newcombe 1998)."""
    if n_t <= 0 or n_c <= 0:
        return None
    p_t, p_c = k_t / n_t, k_c / n_c
    l_t, u_t = wilson(k_t, n_t, z)
    l_c, u_c = wilson(k_c, n_c, z)
    d = p_t - p_c
    lower = d - math.sqrt((p_t - l_t) ** 2 + (u_c - p_c) ** 2)
    upper = d + math.sqrt((u_t - p_t) ** 2 + (p_c - l_c) ** 2)
    return d, max(-1.0, lower), min(1.0, upper)


def bayes_better(k_t: int, n_t: int, k_c: int, n_c: int, *, draws: int = 20000, seed: int = 11) -> dict:
    """P(treatment rate > control rate) and the relative lift's posterior
    median and 95% interval, from Beta(1, 1) priors. Fixed seed: reproducible."""
    import numpy as np

    rng = np.random.default_rng(seed)
    t = rng.beta(1 + k_t, 1 + n_t - k_t, draws)
    c = rng.beta(1 + k_c, 1 + n_c - k_c, draws)
    rel = (t - c) / c
    low, mid, high = np.percentile(rel, [2.5, 50, 97.5])
    return {"prob_better": round(float((t > c).mean()), 4), "relative": (float(mid), float(low), float(high))}


def _chi2_sf(x: float, df: int) -> float:
    """Upper tail of the chi-square distribution for 1 or 2 degrees of freedom."""
    if x <= 0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2))
    if df == 2:
        return math.exp(-x / 2)
    raise ValueError("only 1 or 2 degrees of freedom are needed here")


def srm_p_value(counts: dict[str, int], shares: dict[str, float]) -> float | None:
    """Sample-ratio-mismatch test: chi-square goodness of fit of the arm sizes
    against the declared split. A tiny p-value means the assignment (or the
    data pipeline) is broken and no effect estimate should be trusted."""
    total = sum(counts.get(a, 0) for a in shares)
    if total == 0:
        return None
    x = sum((counts.get(a, 0) - total * s) ** 2 / (total * s) for a, s in shares.items() if s > 0)
    return _chi2_sf(x, len(shares) - 1)


def sample_size_per_arm(baseline: float, min_effect: float, *, alpha: float = 0.05, power: float = 0.8) -> int | None:
    """Units per group to detect an absolute lift of `min_effect` over
    `baseline` (two-sided test of two proportions, normal approximation)."""
    p1, p2 = baseline, baseline + min_effect
    if not (0 < p1 < 1 and 0 < p2 < 1):
        return None
    z_a = {0.05: 1.959963984540054, 0.1: 1.6448536269514722}.get(alpha, 1.959963984540054)
    z_b = {0.8: 0.8416212335729143, 0.9: 1.2815515655446004}.get(power, 0.8416212335729143)
    pbar = (p1 + p2) / 2
    n = (z_a * math.sqrt(2 * pbar * (1 - pbar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
    return math.ceil(n)


# --- Analysis (pure: rows in, result out) ---------------------------------------------------------

def _ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _r(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


def analyze(experiment: dict, assignments: list[dict], events: list[dict], *, now: datetime | None = None) -> dict:
    """The impact report for one experiment. `assignments`: {id, arm};
    `events`: {assignment_id, arm, kind, qualified, value, currency, round_number, occurred_at}."""
    now = now or datetime.now(timezone.utc)
    design = experiment["design"]
    metric = experiment["primary_metric"]
    started = _ts(experiment.get("started_at"))
    analysis_at = _ts(experiment.get("analysis_at"))
    window_end = min(now, analysis_at) if analysis_at else now
    final = bool(analysis_at and now >= analysis_at)
    window_days = int(experiment.get("attribution_window_days") or 7)

    arm_of = {a["id"]: a["arm"] for a in assignments}
    units: dict[str, set] = {arm: set() for arm in ARMS}
    for a in assignments:
        units[a["arm"]].add(a["id"])

    def in_window(e: dict) -> bool:
        t = _ts(e["occurred_at"])
        return bool(started and t and started <= t <= window_end)

    exposed: dict[str, set] = {arm: set() for arm in ARMS}
    clickers: dict[str, set] = {arm: set() for arm in ARMS}
    converters: dict[str, set] = {arm: set() for arm in ARMS}
    qualified: dict[str, set] = {arm: set() for arm in ARMS}
    revenue: dict[str, float] = {}  # per unit, conversions in the window
    currencies: set[str] = set()
    first_click: dict[str, datetime] = {}
    valued: list[tuple[str, datetime, float]] = []  # (unit, when, value) of conversions in the window
    conversions_received = unmatched = 0
    last = {"exposure": None, "click": None, "conversion": None}
    for e in events:
        t = _ts(e["occurred_at"])
        if last.get(e["kind"]) is None or (t and t > last[e["kind"]]):
            last[e["kind"]] = t
        if e["kind"] == "conversion":
            conversions_received += 1
        uid = e.get("assignment_id")
        if uid not in arm_of:
            if e["kind"] == "conversion":
                unmatched += 1
            continue
        arm = arm_of[uid]
        if e["kind"] == "exposure":
            exposed[arm].add(uid)
        if not in_window(e):
            continue
        if e["kind"] == "click":
            clickers[arm].add(uid)
            if uid not in first_click or t < first_click[uid]:
                first_click[uid] = t
        elif e["kind"] == "conversion":
            converters[arm].add(uid)
            if e.get("qualified"):
                qualified[arm].add(uid)
            if e.get("value") is not None:
                revenue[uid] = revenue.get(uid, 0.0) + float(e["value"])
                valued.append((uid, t, float(e["value"])))
                if e.get("currency"):
                    currencies.add(e["currency"])

    success = {"qualified_signup_rate": qualified, "conversion_rate": converters, "click_through_rate": clickers}[metric]
    shares = expected_shares(design, float(experiment.get("control_share") or 0))
    arms_out = {}
    for arm in shares:
        n, k = len(units[arm]), len(success[arm])
        ci = wilson(k, n)
        arms_out[arm] = {
            "units": n, "exposed": len(exposed[arm]), "clickers": len(clickers[arm]), "converters": len(converters[arm]),
            "qualified": len(qualified[arm]), "successes": k, "rate": _r(k / n) if n else None,
            "rate_interval": [_r(ci[0]), _r(ci[1])] if ci else None,
            "revenue": round(sum(revenue.get(u, 0.0) for u in units[arm]), 2),
            "revenue_per_unit": _r(sum(revenue.get(u, 0.0) for u in units[arm]) / n) if n else None,
        }

    def group(arms: tuple[str, ...]) -> tuple[int, int, set]:
        members = set().union(*(units[a] for a in arms))
        return len(members), sum(len(success[a]) for a in arms), members

    def estimate(t_arms: tuple[str, ...], c_arms: tuple[str, ...]) -> dict:
        n_t, k_t, members_t = group(t_arms)
        n_c, k_c, _ = group(c_arms)
        diff = newcombe_diff(k_t, n_t, k_c, n_c)
        out = {
            "treatment_arms": list(t_arms), "control_arms": list(c_arms),
            "treatment_units": n_t, "control_units": n_c, "treatment_successes": k_t, "control_successes": k_c,
            "treatment_rate": _r(k_t / n_t) if n_t else None, "control_rate": _r(k_c / n_c) if n_c else None,
            "absolute_lift": None, "interval": None, "prob_treatment_better": None,
            "relative_lift": None, "relative_interval": None, "relative_note": None,
            "incremental_successes": None, "incremental_interval": None, "causal": True,
        }
        if diff is None:
            return out
        d, lo, hi = diff
        bayes = bayes_better(k_t, n_t, k_c, n_c)
        out.update(absolute_lift=_r(d), interval=[_r(lo), _r(hi)], prob_treatment_better=bayes["prob_better"],
                   incremental_successes=round(d * n_t, 1), incremental_interval=[round(lo * n_t, 1), round(hi * n_t, 1)])
        if k_c >= MIN_BASELINE_SUCCESSES:
            mid, rlo, rhi = bayes["relative"]
            out.update(relative_lift=_r(mid), relative_interval=[_r(rlo), _r(rhi)])
        else:
            out["relative_note"] = "BASELINE_TOO_THIN"
        return out

    t_arms, c_arms = comparison(design)
    primary = estimate(t_arms, c_arms)
    secondary = estimate(("treatment_b",), ("treatment",)) if design == "holdout_ab" else None

    # Revenue: observed per arm; the incremental estimate only from the randomized comparison;
    # attribution (last click before the conversion, within the window) is reported apart and is not causal.
    revenue_out = None
    if revenue:
        n_t, _, members_t = group(t_arms)
        n_c, _, members_c = group(c_arms)
        mixed = len(currencies) > 1
        # Extra conversions (any conversion: revenue isn't only qualified sign-ups), with the
        # same Newcombe interval, times the average value of a converting unit. Assumes the
        # campaign changes how many people buy, not how much each spends.
        conv_t = sum(len(converters[a]) for a in t_arms)
        conv_c = sum(len(converters[a]) for a in c_arms)
        conv = newcombe_diff(conv_t, n_t, conv_c, n_c)
        average = sum(revenue.values()) / len(revenue)
        diff = None if mixed or conv is None else (conv[0] * average, conv[1] * average, conv[2] * average)
        attributed = sum(
            v for u, t, v in valued
            if u in members_t and u in first_click and first_click[u] <= t <= first_click[u] + timedelta(days=window_days)
        )
        revenue_out = {
            "currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "mixed_currencies": mixed,
            "incremental_revenue": round(diff[0] * n_t, 2) if diff else None,
            "incremental_interval": [round(diff[1] * n_t, 2), round(diff[2] * n_t, 2)] if diff else None,
            "average_conversion_value": round(average, 2),
            "attributed_revenue": round(attributed, 2),
            "attribution_model": f"a click before converting, within {window_days} days (not causal)",
        }

    counts = {arm: len(units[arm]) for arm in shares}
    srm_p = srm_p_value(counts, shares)
    stale = bool(
        not final and last["conversion"] and (now - last["conversion"]) > timedelta(hours=STALE_OUTCOME_HOURS)
    )
    quiet = bool(
        not final and metric in CONVERSION_METRICS and conversions_received == 0 and started
        and (now - started) > timedelta(days=3)
    )
    min_units = int(experiment.get("min_units_per_arm") or 0)
    n_small = min(primary["treatment_units"], primary["control_units"])
    quality = {
        "srm_p_value": _r(srm_p, 6), "sample_ratio_mismatch": bool(srm_p is not None and srm_p < SRM_ALPHA),
        "expected_shares": {a: round(s, 4) for a, s in shares.items()}, "min_units_per_arm": min_units,
        "smallest_group": n_small, "conversions_received": conversions_received, "unmatched_conversions": unmatched,
        "last_exposure_at": _iso(last["exposure"]), "last_click_at": _iso(last["click"]),
        "last_conversion_at": _iso(last["conversion"]), "stale_outcomes": stale, "no_conversions_yet": quiet,
    }

    min_effect = float(experiment.get("min_effect") or 0.01)
    if not final:
        status, reason = "COLLECTING", "BEFORE_PREDECLARED_END"
    elif quality["sample_ratio_mismatch"]:
        status, reason = "INCONCLUSIVE", "SAMPLE_RATIO_MISMATCH"
    elif metric in CONVERSION_METRICS and conversions_received == 0:
        status, reason = "INCONCLUSIVE", "NO_OUTCOME_DATA"
    elif n_small < min_units or primary["interval"] is None:
        status, reason = "INCONCLUSIVE", "INSUFFICIENT_DATA"
    elif primary["interval"][0] > 0:
        status, reason = "POSITIVE_IMPACT", "INTERVAL_ABOVE_ZERO"
    elif primary["interval"][1] < 0:
        status, reason = "NEGATIVE_IMPACT", "INTERVAL_BELOW_ZERO"
    elif primary["interval"][0] >= -min_effect and primary["interval"][1] <= min_effect:
        status, reason = "NO_MEANINGFUL_IMPACT", "INTERVAL_WITHIN_MIN_EFFECT"
    else:
        status, reason = "INCONCLUSIVE", "INTERVAL_TOO_WIDE"

    assumptions = ["INTENTION_TO_TREAT", "OUTCOME_WINDOW_FIXED"]
    if design != "ab":
        assumptions += ["CONTROL_SEES_OTHER_CHANNELS", "CONVERSIONS_MATCHED_BY_TOKEN_OR_EMAIL"]
    if unmatched:
        assumptions.append("UNMATCHED_CONVERSIONS_EXCLUDED")

    action = {
        "POSITIVE_IMPACT": "KEEP_AND_EXTEND", "NEGATIVE_IMPACT": "STOP_THIS_APPROACH",
        "NO_MEANINGFUL_IMPACT": "REWORK_OR_STOP", "INCONCLUSIVE": "NO_CLAIM", "COLLECTING": None,
    }[status]
    return {
        "policy_version": POLICY_VERSION, "status": status, "reason": reason, "final": final, "interim": not final,
        "primary_metric": metric, "design": design, "min_effect": min_effect,
        "practically_significant": bool(primary["absolute_lift"] is not None and primary["absolute_lift"] >= min_effect),
        "window": {"started_at": _iso(started), "ends_at": experiment.get("ends_at"), "analysis_at": _iso(analysis_at),
                   "attribution_window_days": window_days},
        "arms": arms_out, "estimate": primary, "secondary": secondary, "revenue": revenue_out,
        "quality": quality, "assumptions": assumptions, "recommended_action": action, "analyzed_at": _iso(now),
    }


def analyze_counts(control_units: int, control_successes: int, treatment_units: int, treatment_successes: int, *,
                   min_effect: float = 0.01, min_units_per_arm: int = 100, metric: str = "conversion_rate",
                   declared_control_share: float | None = None) -> dict:
    """The final read-out for already-aggregated counts from a randomized holdout
    (the MCP tool, and the benchmark's sanity checks): the same analysis as a
    stored experiment, run on equivalent unit rows."""
    if not (0 <= control_successes <= control_units and 0 <= treatment_successes <= treatment_units):
        raise ValueError("successes must be between 0 and the group size")
    total = control_units + treatment_units
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    exp = {"id": "counts", "design": "holdout", "primary_metric": metric,
           "control_share": declared_control_share if declared_control_share is not None else (control_units / total if total else 0.5),
           "attribution_window_days": 7,
           "min_units_per_arm": min_units_per_arm, "min_effect": min_effect,
           "started_at": start.isoformat(), "ends_at": (start + timedelta(days=14)).isoformat(),
           "analysis_at": (start + timedelta(days=21)).isoformat()}
    assignments, events = [], []
    kind = "click" if metric == "click_through_rate" else "conversion"
    for arm, n, k in (("control", control_units, control_successes), ("treatment", treatment_units, treatment_successes)):
        for i in range(n):
            uid = f"{arm}-{i}"
            assignments.append({"id": uid, "arm": arm})
            if i < k:
                events.append({"assignment_id": uid, "arm": arm, "kind": kind, "qualified": True, "value": None,
                               "currency": None, "round_number": 1, "occurred_at": (start + timedelta(days=1)).isoformat()})
    # Without a declared split, the observed one is taken as declared: counts alone can't show a sample-ratio mismatch.
    return analyze(exp, assignments, events, now=start + timedelta(days=22))


def impact_api_view(result: dict | None) -> dict:
    """The shape GET /v1/experiments/{id}/impact returns (also used by the MCP tool)."""
    if not result:
        return {"status": "INCONCLUSIVE", "primaryMetric": None, "controlRate": None, "treatmentRate": None,
                "absoluteLift": None, "confidenceOrCredibleInterval": None, "reason": "NOT_ANALYZED_YET"}
    est = result.get("estimate") or {}
    return {
        "status": result["status"], "reason": result["reason"], "primaryMetric": result["primary_metric"],
        "controlRate": est.get("control_rate"), "treatmentRate": est.get("treatment_rate"),
        "absoluteLift": est.get("absolute_lift"), "confidenceOrCredibleInterval": est.get("interval"),
        "intervalMethod": "newcombe_hybrid_score_95", "probabilityTreatmentBetter": est.get("prob_treatment_better"),
        "relativeLift": est.get("relative_lift"), "final": result.get("final"), "analyzedAt": result.get("analyzed_at"),
    }


# --- Storage and the send path ------------------------------------------------------------------

def _client():
    from src.db.supabase_client import get_client

    return get_client()


def _all(make_query, page: int = 1000) -> list[dict]:
    rows, start = [], 0
    while True:
        batch = make_query().range(start, start + page - 1).execute().data or []
        rows += batch
        if len(batch) < page:
            return rows
        start += page


def experiment_for(campaign_id: str) -> dict | None:
    rows = _client().table("experiments").select("*").eq("campaign_id", campaign_id).limit(1).execute().data or []
    return rows[0] if rows else None


def start(experiment: dict, addresses: list[str]) -> dict[str, dict]:
    """Assign every address (new ones only; existing units keep their arm) and
    start the experiment on its first send. Returns address -> {arm, token, unit_hash}."""
    by_hash = {unit_hash(experiment["id"], a): normalise(a) for a in addresses if a and a.strip()}
    units = [{"unit_hash": h, "arm": assign_arm(experiment["id"], h, experiment["design"], float(experiment["control_share"]))}
             for h in by_hash]
    _client().rpc("start_experiment", {"p_experiment": experiment["id"], "p_units": units}).execute()
    # Read back what's stored (paged: an API response stops at 1000 rows): a unit
    # assigned on an earlier send keeps that arm, whatever was proposed now.
    rows = _all(lambda: _client().table("experiment_assignments").select("unit_hash,arm,token")
                .eq("experiment_id", experiment["id"]).order("unit_hash"))
    return {by_hash[r["unit_hash"]]: {"arm": r["arm"], "token": r["token"], "unit_hash": r["unit_hash"]}
            for r in rows if r["unit_hash"] in by_hash}


def email_groups(campaign_id: str, email_to: list[str], ab: bool) -> tuple[list[str], list[str]] | None:
    """The A and B lists while an experiment runs (control excluded), else None."""
    exp = experiment_for(campaign_id)
    if not exp or not exp.get("started_at"):
        return None
    arms = {r["unit_hash"]: r["arm"] for r in _all(lambda: _client().table("experiment_assignments")
                                                  .select("unit_hash,arm").eq("experiment_id", exp["id"]))}
    a, b = [], []
    for addr in dict.fromkeys(normalise(x) for x in email_to if x and x.strip()):
        arm = arms.get(unit_hash(exp["id"], addr))
        if arm == "treatment" or (arm == "treatment_b" and not ab):
            a.append(addr)
        elif arm == "treatment_b":
            b.append(addr)
    return a, b


def record_exposures(experiment_id: str, round_number: int, unit_hashes: list[str]) -> None:
    try:
        _client().rpc("record_exposures", {"p_experiment": experiment_id, "p_round": round_number,
                                           "p_unit_hashes": unit_hashes}).execute()
    except Exception as exc:  # the email went out; a missing exposure only shows as fewer "exposed"
        logger.warning("recording exposures for %s round %s failed: %s", experiment_id, round_number, exc)


# --- Analysis runs and the bandit ----------------------------------------------------------------

FINISHED = ("completed", "rejected", "blocked")


def run_analysis(experiment: dict, *, now: datetime | None = None) -> dict:
    """Analyse and store. The campaign finishing early pulls the end forward
    (the attribution window still runs in full after the last send)."""
    from src.db.supabase_client import get_campaign

    now = now or datetime.now(timezone.utc)
    new_end = None
    campaign = get_campaign(experiment["campaign_id"])
    if campaign.get("status") in FINISHED and experiment.get("ends_at"):
        finished = _ts(campaign.get("updated_at")) or now
        if finished < _ts(experiment["ends_at"]):
            new_end = finished
            experiment = {**experiment, "ends_at": _iso(finished),
                          "analysis_at": _iso(finished + timedelta(days=int(experiment["attribution_window_days"])))}
    assignments = _all(lambda: _client().table("experiment_assignments").select("id,arm").eq("experiment_id", experiment["id"]))
    events = _all(lambda: _client().table("experiment_events")
                  .select("assignment_id,arm,kind,qualified,value,currency,round_number,occurred_at")
                  .eq("experiment_id", experiment["id"]))
    result = analyze(experiment, assignments, events, now=now)
    if result["final"]:
        result["bandit"] = feed_bandit(experiment, campaign, assignments, events, result)
    _client().rpc("save_impact", {"p_experiment": experiment["id"], "p_result": result, "p_status": result["status"],
                                  "p_final": result["final"], "p_ends_at": _iso(new_end)}).execute()
    if result["final"]:  # a verdict worth remembering is proposed as a lesson (a person confirms it)
        from src.capabilities.brand_memory import lesson_from_experiment

        lesson_from_experiment(experiment, campaign, result)
    return result


def bandit_rewards(experiment: dict, assignments: list[dict], events: list[dict], result: dict) -> list[dict]:
    """The validated reward per round and email variant: of the treatment units
    emailed in that round, the share whose success (the primary metric, in the
    outcome window) came after that round's email and before the next one."""
    arm_of = {a["id"]: a["arm"] for a in assignments}
    metric = experiment["primary_metric"]
    exposures: dict[str, list[tuple[datetime, int]]] = {}
    successes: dict[str, datetime] = {}
    started, end = _ts(experiment.get("started_at")), _ts(result["window"]["analysis_at"])
    for e in events:
        uid, t = e.get("assignment_id"), _ts(e["occurred_at"])
        if uid not in arm_of or arm_of[uid] == "control":
            continue
        if e["kind"] == "exposure":
            exposures.setdefault(uid, []).append((t, int(e.get("round_number") or 0)))
        hit = (
            (metric == "click_through_rate" and e["kind"] == "click")
            or (metric == "conversion_rate" and e["kind"] == "conversion")
            or (metric == "qualified_signup_rate" and e["kind"] == "conversion" and e.get("qualified"))
        )
        if hit and started and t and started <= t <= end and (uid not in successes or t < successes[uid]):
            successes[uid] = t
    cells: dict[tuple[int, str], list[int]] = {}
    for uid, exps in exposures.items():
        exps.sort()
        credited = None
        if uid in successes:
            before = [r for t, r in exps if t <= successes[uid]]
            credited = before[-1] if before else None
        for _, rnd in exps:
            cell = cells.setdefault((rnd, arm_of[uid]), [0, 0])
            cell[1] += 1
            cell[0] += int(rnd == credited)
    return [{"round": r, "arm": arm, "units": n, "successes": k, "reward": round(k / n, 4)}
            for (r, arm), (k, n) in sorted(cells.items()) if n]


def feed_bandit(experiment: dict, campaign: dict, assignments: list[dict], events: list[dict], result: dict) -> dict:
    """Teach the bandit from a valid final result, once. Never raises."""
    if experiment.get("bandit_fed_at"):
        return {"fed": False, "reason": "ALREADY_FED"}
    if result["reason"] in ("SAMPLE_RATIO_MISMATCH", "NO_OUTCOME_DATA"):
        return {"fed": False, "reason": result["reason"]}
    try:
        from src.db.supabase_client import get_personas
        from src.tools.bandit import build_context_vector, update_arm

        rewards = bandit_rewards(experiment, assignments, events, result)
        iterations = {it["round_number"]: it for it in (_client().table("iterations").select("round_number,arm_index,arm_index_b")
                      .eq("campaign_id", experiment["campaign_id"]).execute().data or [])}
        personas = get_personas(experiment["campaign_id"])
        persona = next((p for p in personas if p.get("is_primary")), personas[0] if personas else {})
        context = build_context_vector(persona.get("age_bracket") or "", persona.get("income_tier") or "", "email",
                                       campaign.get("domain_category") or "other")
        fed = []
        for r in rewards:
            it = iterations.get(r["round"]) or {}
            arm_index = it.get("arm_index_b") if r["arm"] == "treatment_b" and it.get("arm_index_b") is not None else it.get("arm_index")
            if arm_index is None:
                continue
            update_arm(int(arm_index), context, r["reward"])
            fed.append({**r, "arm_index": int(arm_index)})
        _client().table("experiments").update({"bandit_fed_at": datetime.now(timezone.utc).isoformat()}).eq("id", experiment["id"]).execute()
        return {"fed": bool(fed), "reward_definition": f"{experiment['primary_metric']} credited to the latest email before the success",
                "rewards": fed}
    except Exception as exc:
        logger.warning("feeding the bandit from experiment %s failed: %s", experiment.get("id"), exc)
        return {"fed": False, "reason": f"ERROR: {type(exc).__name__}"}


def sweep(now: datetime | None = None) -> int:
    """Hourly: analyse every running experiment. One failure never stops the rest."""
    rows = _client().table("experiments").select("*").eq("status", "running").execute().data or []
    done = 0
    for exp in rows:
        try:
            run_analysis(exp, now=now)
            done += 1
        except Exception as exc:
            logger.warning("impact analysis for %s failed: %s", exp.get("id"), exc)
    return done


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    print(f"Proof of impact: analysed {sweep()} running experiment(s).")
