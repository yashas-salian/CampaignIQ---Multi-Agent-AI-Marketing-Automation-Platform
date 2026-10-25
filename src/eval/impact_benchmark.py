"""Benchmark the proof-of-impact engine on synthetic experiments with a known truth.

    python -m src.eval.impact_benchmark          # print the table
    python -m src.eval.impact_benchmark --write  # also update docs/PROOF_OF_IMPACT.md

Each scenario fixes the true conversion rates, the group sizes and the
declared split, then draws many experiments from it (seeded: the same table
every run) and runs each through the engine's final analysis. Reported per
scenario: how often the engine's verdict was right, and how often it made a
false claim (said the campaign helped or hurt when it didn't, or got the sign
wrong). Two common shortcuts run on the same draws as baselines:
  * "point estimate": the campaign worked if its group's rate is higher;
  * "before/after": the campaign worked if the rate during it beats the rate
    before it (no control group). The seasonal scenario is built for it: the
    market rises for everyone and the campaign does nothing.
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.capabilities.impact import POLICY_VERSION, analyze_counts

DOC = Path(__file__).resolve().parents[2] / "docs" / "PROOF_OF_IMPACT.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
DRAWS = 400
SEED = 20261026
CLAIMS = ("POSITIVE_IMPACT", "NEGATIVE_IMPACT")


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    n_control: int
    n_treatment: int
    p_control: float
    p_treatment: float
    truth: str                      # POSITIVE, NEGATIVE, NONE (no effect worth acting on)
    correct: tuple[str, ...]        # verdicts that count as right
    declared_share: float | None = None  # the planned control share, when the real split drifted from it
    p_before: float | None = None   # the rate before the campaign (before/after baseline)
    min_effect: float = 0.01


SCENARIOS = [
    Scenario("null_20_80", "No effect, 20/80 split", 2000, 8000, 0.03, 0.03, "NONE",
             ("NO_MEANINGFUL_IMPACT", "INCONCLUSIVE"), p_before=0.03),
    Scenario("positive", "Real lift, 3% to 5%", 2000, 8000, 0.03, 0.05, "POSITIVE", ("POSITIVE_IMPACT",), p_before=0.03),
    Scenario("negative", "Real harm, 5% to 3%", 2000, 8000, 0.05, 0.03, "NEGATIVE", ("NEGATIVE_IMPACT",), p_before=0.05),
    Scenario("tiny_effect", "Lift below the 1-point bar, big sample", 20000, 20000, 0.030, 0.032, "NONE",
             ("NO_MEANINGFUL_IMPACT", "POSITIVE_IMPACT", "INCONCLUSIVE"), p_before=0.03),
    Scenario("small_sample", "Real lift, only 30 held out", 30, 120, 0.03, 0.06, "POSITIVE",
             ("INCONCLUSIVE",), p_before=0.03),
    Scenario("unequal_5_95", "No effect, 5/95 split", 500, 9500, 0.04, 0.04, "NONE",
             ("NO_MEANINGFUL_IMPACT", "INCONCLUSIVE"), p_before=0.04),
    Scenario("zero_conversions", "No conversions reported at all", 1000, 4000, 0.0, 0.0, "NONE",
             ("INCONCLUSIVE",), p_before=0.0),
    Scenario("broken_split", "Assignment broke: 15% held out, 20% declared", 1500, 8500, 0.03, 0.03, "NONE",
             ("INCONCLUSIVE",), declared_share=0.20, p_before=0.03),
    Scenario("seasonal_rise", "Market rose 2% to 3% for everyone, campaign did nothing", 2000, 8000, 0.03, 0.03, "NONE",
             ("NO_MEANINGFUL_IMPACT", "INCONCLUSIVE"), p_before=0.02),
]


def _point(k_c: int, n_c: int, k_t: int, n_t: int) -> str:
    return "POSITIVE" if k_t / n_t > k_c / n_c else "NEGATIVE" if k_t / n_t < k_c / n_c else "NONE"


def _before_after(k_t: int, n_t: int, k_b: int, n_b: int) -> str:
    return "POSITIVE" if k_t / n_t > k_b / n_b else "NEGATIVE" if k_t / n_t < k_b / n_b else "NONE"


def _false_claim(truth: str, said: str) -> bool:
    """A claim of an effect that isn't there, or of the opposite one."""
    return said in ("POSITIVE", "NEGATIVE") and said != truth


def run(draws: int = DRAWS) -> list[dict]:
    rng = np.random.default_rng(SEED)
    rows = []
    for s in SCENARIOS:
        right = false_claims = point_false = before_false = 0
        reasons: dict[str, int] = {}
        for _ in range(draws):
            n_c, n_t = s.n_control, s.n_treatment
            if s.declared_share is not None:  # the split itself drifted: draw it from the real share
                total = n_c + n_t
                n_c = int(rng.binomial(total, n_c / total))
                n_t = total - n_c
            k_c = int(rng.binomial(n_c, s.p_control))
            k_t = int(rng.binomial(n_t, s.p_treatment))
            result = analyze_counts(n_c, k_c, n_t, k_t, min_effect=s.min_effect, min_units_per_arm=100,
                                    declared_control_share=s.declared_share)
            verdict = result["status"]
            reasons[result["reason"]] = reasons.get(result["reason"], 0) + 1
            right += verdict in s.correct
            said = {"POSITIVE_IMPACT": "POSITIVE", "NEGATIVE_IMPACT": "NEGATIVE"}.get(verdict, "NONE")
            # A real effect too small to matter isn't a false claim when it's real (tiny_effect is "NONE" only for action).
            false_claims += _false_claim(s.truth, said) and not (s.key == "tiny_effect" and said == "POSITIVE")
            point_false += _false_claim(s.truth, _point(k_c, n_c, k_t, n_t))
            k_b = int(rng.binomial(n_t, s.p_before)) if s.p_before is not None else k_c
            before_false += _false_claim(s.truth, _before_after(k_t, n_t, k_b, n_t))
        rows.append({
            "key": s.key, "label": s.label, "truth": s.truth, "draws": draws,
            "engine_right": right / draws, "engine_false_claims": false_claims / draws,
            "point_false_claims": point_false / draws, "before_after_false_claims": before_false / draws,
            "top_reason": max(reasons, key=reasons.get),
        })
    return rows


def table(rows: list[dict]) -> str:
    lines = [
        f"Policy `{POLICY_VERSION}`, {rows[0]['draws']} simulated experiments per scenario (seed {SEED}).",
        "",
        "| Scenario | Truth | Engine right | Engine false claims | Point estimate false claims | Before/after false claims | Engine's usual reason |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['label']} | {r['truth'].lower()} | {r['engine_right']:.0%} | {r['engine_false_claims']:.0%} | "
            f"{r['point_false_claims']:.0%} | {r['before_after_false_claims']:.0%} | `{r['top_reason']}` |"
        )
    # The valid no-effect scenarios (same true rate, usable data): where a 95% interval allows about 5% false claims.
    nulls = [r for r in rows if r["key"] in ("null_20_80", "unequal_5_95", "seasonal_rise")]
    lines += [
        "",
        f"Across the three no-effect scenarios with usable data the engine claimed an effect in "
        f"{sum(r['engine_false_claims'] for r in nulls) / len(nulls):.1%} of experiments; "
        f"the point estimate did in {sum(r['point_false_claims'] for r in nulls) / len(nulls):.0%} "
        f"and before/after in {sum(r['before_after_false_claims'] for r in nulls) / len(nulls):.0%}.",
    ]
    return "\n".join(lines)


def main() -> None:
    out = table(run())
    print(out)
    if "--write" in sys.argv:
        text = DOC.read_text(encoding="utf-8")
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        DOC.write_text(f"{head}{START}\n{out}\n{END}{tail}", encoding="utf-8")
        print(f"\nUpdated {DOC}")


if __name__ == "__main__":
    main()
