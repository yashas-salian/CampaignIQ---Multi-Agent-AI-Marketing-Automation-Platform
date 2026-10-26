"""Creative fatigue: is an ad concept wearing out on the audience that keeps seeing it?

Novelty (src/graph/nodes/novelty_check.py) stops near-duplicates before they're
made. Fatigue is a different question: a concept can be original and still lose
effect as the same people see it round after round, or be repeated and keep
working. This module answers it from results, with policy `fatigue-v1`:

  Unit       a channel and audience segment (email variant A / B), its rounds
             as exposure periods
  Measure    click rate with a real denominator: unique clickers / people
             emailed when the proof-of-impact experiment tracks people, else
             clicks / recipients (capped). Social channels report no
             impressions, so their trend is shown but never called fatigue.
  Baseline   the concept's own first rounds, when it was fresh
  Rule       at least 3 valid rounds (each 100+ people, metrics present); the
             recent rounds *all* below the baseline (sustained, not one bad
             round); a relative drop of 20%+ whose 95% interval excludes zero
             (Newcombe); the recent creatives similar to the fresh ones
             (copy meaning, visual, hook, offer, CTA); and the drop specific
             to this creative: if the other variant or the organisation's
             other emails dropped about as much, it's the market or the
             audience, not the ad.

Results: NO_FATIGUE, FATIGUE_SUSPECTED (sustained and large but not yet
significant), FATIGUE_CONFIRMED, NOT_ATTRIBUTABLE (a real drop the creative
doesn't explain), INSUFFICIENT_DATA, NOT_MEASURABLE (no denominator).
Recommendation: KEEP, TEST_REFRESH or RETIRE (confirmed and near-identical).
Near-duplicates are listed apart, whatever the performance.

A refresh is an intervention: the next round's creative changes the most
repeated feature (NEW_HOOK, NEW_VISUAL, NEW_ANGLE, NEW_OFFER_FRAMING) through
the normal pipeline, guardrails and gates. Its round is then compared with the
fatigued rounds before calling it IMPROVED (interval above zero), WORSE,
NO_CHANGE or INCONCLUSIVE, and the outcomes per channel and industry steer the
next choice of strategy.
"""
import logging
import re
from datetime import datetime, timezone

from src.capabilities.impact import newcombe_diff, wilson

logger = logging.getLogger("capabilities.fatigue")

POLICY_VERSION = "fatigue-v1"
MIN_EXPOSURES = 100
MIN_PERIODS = 3
MIN_RELATIVE_DROP = 0.20
SUSTAINED_MARGIN = 0.10     # each recent round at least this far below the fresh baseline
Z80 = 1.2815515655446004    # FATIGUE_SUSPECTED needs the drop clear of zero at 80%; CONFIRMED at 95%
Z_ROUND = 0.8416212335729143  # each recent round below the baseline, one-sided 80%
SPECIFICITY_MARGIN = 0.15   # another segment's drop within this of ours: not specific to the creative
SAME_CONCEPT = 0.70         # combined similarity at which recent creatives are "the same concept"
NEAR_DUPLICATE = 0.85       # the novelty check's threshold
STRATEGIES = ("NEW_HOOK", "NEW_VISUAL", "NEW_ANGLE", "NEW_OFFER_FRAMING")
WEIGHTS = {"copy": 0.35, "visual": 0.25, "hook": 0.2, "offer": 0.1, "cta": 0.1}

_OFFER = re.compile(r"(\d{1,2}\s?% off|free (?:trial|shipping|delivery|month)|first (?:month|order|box) free|buy one,? get one|"
                    r"save \$?\d+|half price|\d+ ?% discount)", re.I)


# --- Creative features and similarity --------------------------------------------------------

def features(iteration: dict, variant: str = "a") -> dict:
    """What a round's creative was made of (variant B has its own copy and arm)."""
    b = variant == "b"
    copy = (iteration.get("copy_text_b") if b else iteration.get("copy_text")) or ""
    hook = re.split(r"(?<=[.!?])\s+", copy.strip(), maxsplit=1)[0] if copy.strip() else ""
    offer = _OFFER.search(copy)
    return {
        "round": iteration.get("round_number"),
        "copy": copy,
        "hook": hook[:200],
        "offer": offer.group(0).lower() if offer else None,
        "cta": (iteration.get("cta") or "").strip().lower(),
        "template": None if b else iteration.get("template"),
        "image_style": iteration.get("image_style_b") if b else iteration.get("image_style"),
        "copy_tone": iteration.get("copy_tone_b") if b else iteration.get("copy_tone"),
        "arm_index": iteration.get("arm_index_b") if b else iteration.get("arm_index"),
    }


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def text_similarity(texts: list[str]) -> list[list[float]]:
    """Meaning similarity of copies (the novelty check's multilingual embeddings);
    word overlap if the model can't load."""
    try:
        from src.tools.memory import embed_texts

        vecs = embed_texts(texts)
        return (vecs @ vecs.T).tolist()
    except Exception as exc:
        logger.warning("embeddings unavailable, using word overlap: %s", exc)
        return [[_jaccard(a, b) for b in texts] for a in texts]


def similarity(fa: dict, fb: dict, copy_sim: float) -> dict:
    """Per-feature similarity of two creatives and the weighted total."""
    visual = 1.0 if fa.get("template") and fa.get("template") == fb.get("template") else (
        0.6 if fa.get("image_style") and fa.get("image_style") == fb.get("image_style") else 0.0)
    parts = {
        "copy": round(max(0.0, min(1.0, copy_sim)), 3),
        "visual": visual,
        "hook": round(_jaccard(fa.get("hook") or "", fb.get("hook") or ""), 3),
        "cta": 1.0 if fa.get("cta") and fa.get("cta") == fb.get("cta") else 0.0,
    }
    weights = dict(WEIGHTS)
    if fa.get("offer") or fb.get("offer"):  # no offer in either: the feature says nothing
        parts["offer"] = 1.0 if fa.get("offer") == fb.get("offer") else 0.0
    else:
        weights.pop("offer")
    total = sum(weights[k] * parts[k] for k in weights) / sum(weights.values())
    return {**parts, "total": round(total, 3)}


def duplicates(creatives: list[dict], sims: list[list[float]]) -> list[dict]:
    """Near-duplicates, reported apart from fatigue (performance doesn't enter)."""
    out = []
    for j in range(1, len(creatives)):
        best = max(range(j), key=lambda i: similarity(creatives[i], creatives[j], sims[i][j])["total"])
        s = similarity(creatives[best], creatives[j], sims[best][j])
        if s["total"] >= NEAR_DUPLICATE:
            out.append({"round": creatives[j]["round"], "of_round": creatives[best]["round"], "similarity": s})
    return out


# --- The rule (pure) --------------------------------------------------------------------------

def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def relative_drop(periods: list[dict]) -> float | None:
    """(baseline - recent) / baseline for a list of periods, same split as the rule."""
    valid = [p for p in periods if (p.get("exposures") or 0) >= MIN_EXPOSURES and not p.get("stale")]
    if len(valid) < 2:
        return None
    base, recent = (valid[:2], valid[-2:]) if len(valid) >= 4 else (valid[:1], valid[1:][-2:])
    rb = _rate(sum(p["successes"] for p in base), sum(p["exposures"] for p in base))
    rr = _rate(sum(p["successes"] for p in recent), sum(p["exposures"] for p in recent))
    return None if not rb else (rb - rr) / rb


def analyze_segment(periods: list[dict], *, similarity_to_fresh: float | None, comparators: list[float | None] = ()) -> dict:
    """periods: [{round, exposures (None = no denominator), successes, stale}] oldest first.
    comparators: relative drops of the other variant / the organisation's other emails over the same rounds."""
    out = {"periods": periods, "status": None, "reason": None, "recommendation": "KEEP", "baseline": None, "recent": None,
           "relative_drop": None, "interval": None, "sustained": None, "similarity_to_fresh": similarity_to_fresh,
           "comparators": [c for c in comparators if c is not None], "min_exposures": MIN_EXPOSURES, "min_periods": MIN_PERIODS}
    if periods and all(p.get("exposures") is None for p in periods):
        return {**out, "status": "NOT_MEASURABLE", "reason": "NO_EXPOSURE_DATA"}
    valid = [p for p in periods if (p.get("exposures") or 0) >= MIN_EXPOSURES and not p.get("stale")]
    if len(valid) < MIN_PERIODS:
        reason = "STALE_OR_MISSING_METRICS" if any(p.get("stale") for p in periods) else "TOO_FEW_ROUNDS_OR_PEOPLE"
        return {**out, "status": "INSUFFICIENT_DATA", "reason": reason}

    base, recent = (valid[:2], valid[-2:]) if len(valid) >= 4 else (valid[:1], valid[1:][-2:])
    kb, nb = sum(p["successes"] for p in base), sum(p["exposures"] for p in base)
    kr, nr = sum(p["successes"] for p in recent), sum(p["exposures"] for p in recent)
    rb, rr = kb / nb, kr / nr
    diff = newcombe_diff(kr, nr, kb, nb)
    diff80 = newcombe_diff(kr, nr, kb, nb, z=Z80)
    drop = (rb - rr) / rb if rb else 0.0
    # Sustained: every recent round on its own clearly below the fresh baseline (beyond its noise,
    # one-sided 80%, and by 10%+): one bad round followed by an ordinary one isn't a trend.
    sustained = all(
        p["successes"] / p["exposures"] <= rb * (1 - SUSTAINED_MARGIN)
        and newcombe_diff(p["successes"], p["exposures"], kb, nb, z=Z_ROUND)[2] < 0
        for p in recent
    )
    ci_b, ci_r = wilson(kb, nb), wilson(kr, nr)
    out.update(
        baseline={"rounds": [p["round"] for p in base], "rate": round(rb, 4), "interval": [round(ci_b[0], 4), round(ci_b[1], 4)]},
        recent={"rounds": [p["round"] for p in recent], "rate": round(rr, 4), "interval": [round(ci_r[0], 4), round(ci_r[1], 4)]},
        relative_drop=round(drop, 4), interval=[round(diff[1], 4), round(diff[2], 4)], sustained=sustained,
    )
    significant = diff[2] < 0
    meaningful = drop >= MIN_RELATIVE_DROP
    if not (sustained and meaningful):
        return {**out, "status": "NO_FATIGUE", "reason": "NO_SUSTAINED_DROP" if not sustained else "DROP_TOO_SMALL"}
    if any(c is not None and c >= drop - SPECIFICITY_MARGIN for c in comparators):
        return {**out, "status": "NOT_ATTRIBUTABLE", "reason": "MARKET_OR_AUDIENCE_DROP"}
    if similarity_to_fresh is not None and similarity_to_fresh < SAME_CONCEPT:
        return {**out, "status": "NOT_ATTRIBUTABLE", "reason": "CREATIVES_DIFFER"}
    if significant:
        retire = similarity_to_fresh is not None and similarity_to_fresh >= NEAR_DUPLICATE
        return {**out, "status": "FATIGUE_CONFIRMED", "reason": "SIGNIFICANT_SUSTAINED_DROP",
                "recommendation": "RETIRE" if retire else "TEST_REFRESH"}
    if diff80[2] < 0:  # clear at 80% but not yet at 95%: worth a cheap test, not a verdict
        return {**out, "status": "FATIGUE_SUSPECTED", "reason": "SUSTAINED_DROP_NOT_YET_SIGNIFICANT", "recommendation": "TEST_REFRESH"}
    return {**out, "status": "NO_FATIGUE", "reason": "DROP_WITHIN_NOISE"}


# --- Refresh strategy ---------------------------------------------------------------------------

_FEATURE_STRATEGY = {"hook": "NEW_HOOK", "copy": "NEW_ANGLE", "visual": "NEW_VISUAL", "offer": "NEW_OFFER_FRAMING", "cta": "NEW_HOOK"}


def suggested_strategy(sim: dict | None, learned: dict[str, tuple[int, int]] | None = None) -> tuple[str, dict]:
    """Change what repeats most; past outcomes in this context break ties and can
    override (Beta(1, 1) posterior mean of 'improved', with 2+ tries)."""
    order = []
    if sim:
        ranked = sorted((k for k in WEIGHTS if k in sim), key=lambda k: -sim[k])
        order = list(dict.fromkeys(_FEATURE_STRATEGY[k] for k in ranked))
    order += [s for s in STRATEGIES if s not in order]
    scores = {}
    for s in STRATEGIES:
        won, tried = (learned or {}).get(s, (0, 0))
        scores[s] = {"improved": won, "tried": tried, "posterior_mean": round((1 + won) / (2 + tried), 3)}
    proven = [s for s in order if scores[s]["tried"] >= 2]
    best = max(proven, key=lambda s: (scores[s]["posterior_mean"], -order.index(s))) if proven else None
    pick = best if best and scores[best]["posterior_mean"] > 0.5 else order[0]
    return pick, scores


def refresh_constraints(fresh: list[dict], recent: list[dict]) -> dict:
    """What the refreshed creative must not repeat (our own past creatives only)."""
    seen = fresh + recent
    return {
        "avoid_hooks": list(dict.fromkeys(f["hook"] for f in seen if f.get("hook")))[:3],
        "avoid_offers": list(dict.fromkeys(f["offer"] for f in seen if f.get("offer")))[:3],
        "avoid_styles": list(dict.fromkeys(f["image_style"] for f in seen if f.get("image_style"))),
        "avoid_tones": list(dict.fromkeys(f["copy_tone"] for f in seen if f.get("copy_tone"))),
        "avoid_templates": list(dict.fromkeys(f["template"] for f in seen if f.get("template"))),
    }


def refresh_directive(strategy: str, constraints: dict) -> str:
    """Guidance for the next round's creative (passed as revision guidance: the
    guardrails, pre-flight, crash test and Gate 2 all still apply)."""
    hooks = "; ".join(f"“{h}”" for h in constraints.get("avoid_hooks", []))
    offers = "; ".join(f"“{o}”" for o in constraints.get("avoid_offers", []))
    base = "The audience has seen this ad concept for several rounds and responds less each time. "
    if strategy == "NEW_HOOK":
        return base + f"Open with a clearly different first sentence than {hooks or 'the previous rounds'}; keep the facts the same."
    if strategy == "NEW_OFFER_FRAMING":
        return base + (f"Lead with a different benefit instead of {offers}. " if offers else "Lead with a different benefit. ") + \
            "Do not invent offers, prices or deadlines."
    if strategy == "NEW_VISUAL":
        return base + "Use a visibly different picture and layout from the previous rounds."
    return base + "Take a different angle and tone from the previous rounds; keep the facts the same."


def pick_arm(strategy: str, constraints: dict, candidates: list[tuple[int, str, str]]) -> tuple[int, str, str] | None:
    """For a visual or angle refresh: the best-ranked arm that changes the style / the tone."""
    if strategy == "NEW_VISUAL":
        avoid = set(constraints.get("avoid_styles", []))
        return next((a for a in candidates if a[1] not in avoid), None)
    if strategy == "NEW_ANGLE":
        avoid = set(constraints.get("avoid_tones", []))
        return next((a for a in candidates if a[2] not in avoid), None)
    return None


def evaluate_refresh(before: tuple[int, int], after: tuple[int, int], fresh_rate: float | None) -> dict:
    """The refreshed round against the fatigued rounds it replaced (same audience,
    next period: a sequential comparison, labelled as such). IMPROVED only when
    the 95% interval of the change is above zero."""
    (kb, nb), (ka, na) = before, after
    if na < MIN_EXPOSURES or nb < MIN_EXPOSURES:
        return {"outcome": "INCONCLUSIVE", "reason": "TOO_FEW_PEOPLE", "design": "sequential"}
    d = newcombe_diff(ka, na, kb, nb)
    rate_before, rate_after = kb / nb, ka / na
    if d[1] > 0:
        outcome = "IMPROVED"
    elif d[2] < 0:
        outcome = "WORSE"
    elif rate_before and abs(d[1]) <= MIN_RELATIVE_DROP * rate_before and abs(d[2]) <= MIN_RELATIVE_DROP * rate_before:
        outcome = "NO_CHANGE"
    else:
        outcome = "INCONCLUSIVE"
    return {"outcome": outcome, "design": "sequential", "rate_before": round(rate_before, 4), "rate_after": round(rate_after, 4),
            "change": round(d[0], 4), "interval": [round(d[1], 4), round(d[2], 4)],
            "recovered_to_fresh": bool(fresh_rate and rate_after >= fresh_rate)}


# --- Gathering the data (I/O) ---------------------------------------------------------------------

def _client():
    from src.db.supabase_client import get_client

    return get_client()


def _parse(ts) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def email_periods(campaign_id: str, iterations: list[dict], metrics: list[dict], variant: str) -> list[dict]:
    """Per round: people emailed and how many clicked. Unique people from the
    experiment's events when it tracks them; else clicks over recipients."""
    from src.capabilities.impact import experiment_for

    channel = "email" if variant == "a" else "email_b"
    exp = None
    try:
        exp = experiment_for(campaign_id)
    except Exception:
        pass
    tracked: dict[int, tuple[int, int]] = {}
    if exp and exp.get("started_at"):
        arm = "treatment" if variant == "a" else "treatment_b"
        from src.capabilities.impact import _all

        events = _all(lambda: _client().table("experiment_events").select("assignment_id,kind,round_number,arm")
                      .eq("experiment_id", exp["id"]).eq("arm", arm).in_("kind", ["exposure", "click"]))
        for rnd in {e["round_number"] for e in events if e.get("round_number")}:
            exposed = {e["assignment_id"] for e in events if e["kind"] == "exposure" and e["round_number"] == rnd}
            clicked = {e["assignment_id"] for e in events if e["kind"] == "click" and e["round_number"] == rnd} & exposed
            tracked[rnd] = (len(exposed), len(clicked))
    by_round = {m["round_number"]: m for m in metrics if m["channel"] == channel}
    periods = []
    for it in sorted(iterations, key=lambda i: i["round_number"]):
        rnd = it["round_number"]
        if variant == "b" and not it.get("copy_text_b"):
            continue
        if rnd in tracked:
            n, k = tracked[rnd]
            periods.append({"round": rnd, "exposures": n, "successes": k, "unique": True, "stale": False})
            continue
        m = by_round.get(rnd)
        if not m:
            periods.append({"round": rnd, "exposures": 0, "successes": 0, "unique": False, "stale": True})
            continue
        raw = m.get("raw_metrics") or {}
        n = int(raw.get("recipients") or 0)
        periods.append({"round": rnd, "exposures": n, "successes": min(int(raw.get("clicks") or 0), n), "unique": False, "stale": False})
    return periods


def social_periods(channel: str, metrics: list[dict]) -> list[dict]:
    """Engagement per round with no denominator: shown, never judged."""
    keys = ("likes", "reposts", "replies", "score", "num_comments")
    return [{"round": m["round_number"], "exposures": None, "successes": None, "stale": False,
             "engagement": sum(int((m.get("raw_metrics") or {}).get(k) or 0) for k in keys)}
            for m in sorted((m for m in metrics if m["channel"] == channel), key=lambda m: m["round_number"])]


def org_email_drop(org_id: str | None, campaign_id: str, rounds_at: dict[int, datetime], base_rounds: list[int], recent_rounds: list[int]) -> float | None:
    """How much the organisation's other emails dropped between the same two windows."""
    if not org_id or not base_rounds or not recent_rounds:
        return None
    try:
        lo_b = min(rounds_at[r] for r in base_rounds if r in rounds_at)
        hi_b = max(rounds_at[r] for r in base_rounds if r in rounds_at)
        lo_r = min(rounds_at[r] for r in recent_rounds if r in rounds_at)
        hi_r = max(rounds_at[r] for r in recent_rounds if r in rounds_at)
    except ValueError:
        return None
    others = (_client().table("metrics").select("campaign_id,raw_metrics,collected_at,campaigns!inner(org_id)")
              .eq("campaigns.org_id", org_id).eq("channel", "email").neq("campaign_id", campaign_id).execute().data or [])

    def pooled(lo, hi):
        rows = [r for r in others if lo <= (_parse(r["collected_at"]) or lo) <= hi]
        n = sum(int((r["raw_metrics"] or {}).get("recipients") or 0) for r in rows)
        k = sum(min(int((r["raw_metrics"] or {}).get("clicks") or 0), int((r["raw_metrics"] or {}).get("recipients") or 0)) for r in rows)
        return (k, n) if n >= MIN_EXPOSURES else None

    b, r = pooled(lo_b, hi_b), pooled(lo_r, hi_r)
    if not b or not r or not b[0]:
        return None
    return (b[0] / b[1] - r[0] / r[1]) / (b[0] / b[1])


def learned_outcomes(org_id: str | None, channel: str, domain: str) -> dict[str, tuple[int, int]]:
    if not org_id:
        return {}
    rows = (_client().table("creative_interventions").select("strategy,outcome").eq("org_id", org_id).eq("channel", channel)
            .eq("domain_category", domain).in_("outcome", ["IMPROVED", "NO_CHANGE", "WORSE"]).execute().data or [])
    out: dict[str, tuple[int, int]] = {}
    for r in rows:
        won, tried = out.get(r["strategy"], (0, 0))
        out[r["strategy"]] = (won + (r["outcome"] == "IMPROVED"), tried + 1)
    return out


def analyze_campaign(campaign: dict, *, text_sim=text_similarity) -> dict:
    client = _client()
    iterations = (client.table("iterations").select("*").eq("campaign_id", campaign["id"]).order("round_number")
                  .order("preflight_attempt", desc=True).execute().data or [])
    latest = {}
    for it in iterations:  # the creative that went out: the last pre-flight attempt of each round
        latest.setdefault(it["round_number"], it)
    iterations = [latest[r] for r in sorted(latest)]
    metrics = client.table("metrics").select("*").eq("campaign_id", campaign["id"]).execute().data or []
    rounds_at = {m["round_number"]: _parse(m["collected_at"]) for m in metrics if m.get("collected_at")}

    segments, all_creatives = [], []
    variants = ["a"] + (["b"] if any(it.get("copy_text_b") for it in iterations) else [])
    for variant in variants:
        creatives = [features(it, variant) for it in iterations if variant == "a" or it.get("copy_text_b")]
        all_creatives += creatives
        periods = email_periods(campaign["id"], iterations, metrics, variant)
        sims = text_sim([c["copy"] or " " for c in creatives]) if len(creatives) > 1 else [[1.0]]
        valid = [p for p in periods if (p.get("exposures") or 0) >= MIN_EXPOSURES and not p.get("stale")]
        base_r = [p["round"] for p in (valid[:2] if len(valid) >= 4 else valid[:1])]
        recent_r = [p["round"] for p in valid[-2:]] if len(valid) >= 2 else []
        idx = {c["round"]: i for i, c in enumerate(creatives)}
        pair_sims = [similarity(creatives[idx[b]], creatives[idx[r]], sims[idx[b]][idx[r]])
                     for b in base_r for r in recent_r if b in idx and r in idx and b != r]
        # Averaged over the fresh-vs-recent pairs; a feature no pair had (no offer anywhere) is left out, not shown as 0.
        mean_sim = ({k: round(sum(s[k] for s in pair_sims if k in s) / sum(1 for s in pair_sims if k in s), 3)
                     for k in list(WEIGHTS) + ["total"] if any(k in s for s in pair_sims)} if pair_sims else None)
        segments.append({"channel": "email", "segment": variant, "periods": periods, "base_rounds": base_r, "recent_rounds": recent_r,
                         "similarity": mean_sim, "creatives": creatives})
    drops = {s["segment"]: relative_drop(s["periods"]) for s in segments}
    results = []
    for s in segments:
        other = [d for k, d in drops.items() if k != s["segment"]]
        bench = org_email_drop(campaign.get("org_id"), campaign["id"], rounds_at, s["base_rounds"], s["recent_rounds"])
        verdict = analyze_segment(s["periods"], similarity_to_fresh=(s["similarity"] or {}).get("total"), comparators=other + [bench])
        fresh = [c for c in s["creatives"] if c["round"] in s["base_rounds"]]
        recent = [c for c in s["creatives"] if c["round"] in s["recent_rounds"]]
        strategy, learned = suggested_strategy(s["similarity"], learned_outcomes(campaign.get("org_id"), "email", campaign.get("domain_category") or "other"))
        results.append({**verdict, "channel": "email", "segment": s["segment"], "similarity": s["similarity"],
                        "comparator_drops": {"other_variant": other[0] if other else None, "organisation_email": bench},
                        "suggested_strategy": strategy, "strategy_record": learned,
                        "refresh_constraints": refresh_constraints(fresh, recent)})
    for ch in sorted({m["channel"] for m in metrics if m["channel"] not in ("email", "email_b")}):
        results.append({**analyze_segment(social_periods(ch, metrics), similarity_to_fresh=None), "channel": ch, "segment": "all"})
    a_creatives = [features(it) for it in iterations]
    dup = duplicates(a_creatives, text_sim([c["copy"] or " " for c in a_creatives])) if len(a_creatives) > 1 else []
    return {"policy_version": POLICY_VERSION, "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "segments": [{k: v for k, v in r.items() if k != "creatives"} for r in results], "duplicates": dup}


def run(campaign_id: str, *, text_sim=text_similarity) -> dict | None:
    """After a round's metrics: analyse, store, raise or refresh alerts, propose a
    refresh for a new alert, and measure a refresh whose round has results. Never raises."""
    try:
        from src.db.supabase_client import get_campaign

        campaign = get_campaign(campaign_id)
        report = analyze_campaign(campaign, text_sim=text_sim)
        client = _client()
        client.table("creative_fatigue_reports").upsert({"campaign_id": campaign_id, "org_id": campaign.get("org_id"),
                                                         "policy_version": POLICY_VERSION, "result": report}).execute()
        for seg in report["segments"]:
            if seg["status"] not in ("FATIGUE_SUSPECTED", "FATIGUE_CONFIRMED"):
                continue
            evidence = {k: seg[k] for k in ("status", "reason", "baseline", "recent", "relative_drop", "interval", "similarity",
                                            "comparator_drops", "suggested_strategy", "refresh_constraints")}
            open_alerts = (client.table("creative_fatigue_alerts").select("id,state").eq("campaign_id", campaign_id)
                           .eq("channel", seg["channel"]).eq("segment", seg["segment"]).in_("state", ["open", "refreshing"]).execute().data or [])
            if open_alerts:
                client.table("creative_fatigue_alerts").update({"status": seg["status"], "recommendation": seg["recommendation"],
                                                                "evidence": evidence, "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", open_alerts[0]["id"]).execute()
                continue
            alert = client.table("creative_fatigue_alerts").insert({
                "campaign_id": campaign_id, "org_id": campaign.get("org_id"), "channel": seg["channel"], "segment": seg["segment"],
                "status": seg["status"], "recommendation": seg["recommendation"], "evidence": evidence}).execute().data[0]
            if campaign.get("status") not in ("completed", "rejected", "blocked"):
                pending = (client.table("creative_interventions").select("id").eq("campaign_id", campaign_id).eq("outcome", "pending")
                           .is_("applied_round", "null").execute().data or [])
                if not pending:  # the system proposes the refresh; people can change or dismiss it before the next round
                    client.table("creative_interventions").insert({
                        "alert_id": alert["id"], "campaign_id": campaign_id, "org_id": campaign.get("org_id"), "channel": seg["channel"],
                        "segment": seg["segment"], "domain_category": campaign.get("domain_category") or "other",
                        "strategy": seg["suggested_strategy"], "constraints": seg["refresh_constraints"]}).execute()
                    client.table("creative_fatigue_alerts").update({"state": "refreshing"}).eq("id", alert["id"]).execute()
        measure_refreshes(campaign, report)
        return report
    except Exception as exc:
        logger.warning("creative fatigue for %s failed: %s", campaign_id, exc)
        return None


def measure_refreshes(campaign: dict, report: dict) -> None:
    client = _client()
    rows = (client.table("creative_interventions").select("*").eq("campaign_id", campaign["id"]).eq("outcome", "pending")
            .not_.is_("applied_round", "null").execute().data or [])
    for iv in rows:
        seg = next((s for s in report["segments"] if s["channel"] == iv["channel"] and s["segment"] == iv["segment"]), None)
        if not seg:
            continue
        after = next((p for p in seg["periods"] if p["round"] == iv["applied_round"] and not p.get("stale")), None)
        if not after:
            continue  # its round's results aren't in yet
        before = [p for p in seg["periods"] if p["round"] < iv["applied_round"] and not p.get("stale")][-2:]
        if not before:
            continue
        result = evaluate_refresh((sum(p["successes"] for p in before), sum(p["exposures"] for p in before)),
                                  (after["successes"], after["exposures"]), (seg.get("baseline") or {}).get("rate"))
        client.table("creative_interventions").update({"outcome": result["outcome"], "outcome_detail": result,
                                                       "measured_at": datetime.now(timezone.utc).isoformat()}).eq("id", iv["id"]).execute()
        if iv.get("alert_id"):
            client.table("creative_fatigue_alerts").update({"state": "closed", "updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", iv["alert_id"]).execute()
        from src.capabilities.brand_memory import lesson_from_refresh  # proposed; a person confirms it

        lesson_from_refresh({**iv, "outcome": result["outcome"], "outcome_detail": result,
                             "measured_at": datetime.now(timezone.utc).isoformat()}, campaign)


def apply_pending_refresh(campaign_id: str, round_number: int, candidates_fn=None) -> tuple[str | None, tuple[int, str, str] | None]:
    """Before the next round's creative: (extra revision guidance, arm override)
    for a waiting refresh, marked as applied to this round. Never raises."""
    try:
        client = _client()
        rows = (client.table("creative_interventions").select("*").eq("campaign_id", campaign_id).eq("outcome", "pending")
                .is_("applied_round", "null").limit(1).execute().data or [])
        if not rows:
            return None, None
        iv = rows[0]
        arm = pick_arm(iv["strategy"], iv.get("constraints") or {}, candidates_fn() if candidates_fn else [])
        client.table("creative_interventions").update({"applied_round": round_number}).eq("id", iv["id"]).execute()
        return refresh_directive(iv["strategy"], iv.get("constraints") or {}), arm
    except Exception as exc:
        logger.warning("refresh for %s not applied: %s", campaign_id, exc)
        return None, None
