"""Benchmark the creative-fatigue rule on synthetic campaigns with a known truth.

    python -m src.eval.fatigue_benchmark          # print the table
    python -m src.eval.fatigue_benchmark --write  # also update docs/CREATIVE_FATIGUE.md

Each scenario fixes the true click rate of every round, how many people each
round reaches, how alike the creatives are and what the comparison segments
did; each draw then samples the clicks (seeded, so the table is the same every
run). Reported per scenario: how often the engine raised a fatigue alert
(FATIGUE_SUSPECTED or FATIGUE_CONFIRMED) and how often a naive rule would:
"the latest round did worse than the one before".
"""
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from src.capabilities.fatigue import POLICY_VERSION, analyze_segment

DOC = Path(__file__).resolve().parents[2] / "docs" / "CREATIVE_FATIGUE.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
DRAWS = 400
SEED = 20261027


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    rates: tuple[float, ...]
    people: int
    similarity: float | None
    truth: bool                      # is this creative fatigue?
    comparator_drop: float | None = None
    no_denominator: bool = False


SCENARIOS = [
    Scenario("steady", "Steady concept, no change", (0.05, 0.05, 0.05, 0.05, 0.05), 400, 0.9, False),
    Scenario("worn_out", "Same concept wearing out (-50% by round 5)", (0.06, 0.06, 0.045, 0.036, 0.03), 400, 0.9, True),
    Scenario("worn_out_variant", "Similar but not identical concept wearing out", (0.06, 0.06, 0.042, 0.036, 0.03), 400, 0.78, True),
    Scenario("one_bad_round", "One bad round, then back to normal", (0.05, 0.05, 0.05, 0.03, 0.05), 400, 0.9, False),
    Scenario("market_drop", "Everyone's emails dropped 45% (the market)", (0.06, 0.06, 0.045, 0.036, 0.033), 400, 0.9, False, 0.42),
    Scenario("creatives_differ", "Decline, but every round's ad was different", (0.06, 0.06, 0.045, 0.036, 0.03), 400, 0.35, False),
    Scenario("mild_dip", "A 10% dip, within normal variation", (0.05, 0.05, 0.05, 0.045, 0.045), 400, 0.9, False),
    Scenario("small_list", "Wearing out, but only 60 people per round", (0.06, 0.06, 0.045, 0.036, 0.03), 60, 0.9, True),
    Scenario("social", "A social channel: likes falling, no impressions", (0.06, 0.06, 0.045, 0.036, 0.03), 400, 0.9, True, None, True),
]


def run(draws: int = DRAWS) -> list[dict]:
    rng = np.random.default_rng(SEED)
    rows = []
    for s in SCENARIOS:
        alarms = naive = 0
        statuses: dict[str, int] = {}
        for _ in range(draws):
            clicks = [int(rng.binomial(s.people, r)) for r in s.rates]
            periods = [{"round": i + 1, "exposures": None if s.no_denominator else s.people,
                        "successes": None if s.no_denominator else k, "stale": False} for i, k in enumerate(clicks)]
            v = analyze_segment(periods, similarity_to_fresh=s.similarity, comparators=[s.comparator_drop])
            statuses[v["status"]] = statuses.get(v["status"], 0) + 1
            alarms += v["status"] in ("FATIGUE_SUSPECTED", "FATIGUE_CONFIRMED")
            naive += clicks[-1] < clicks[-2]
        rows.append({"key": s.key, "label": s.label, "truth": s.truth, "draws": draws, "engine_alarm": alarms / draws,
                     "naive_alarm": naive / draws, "top_status": max(statuses, key=statuses.get)})
    return rows


def table(rows: list[dict]) -> str:
    lines = [
        f"Policy `{POLICY_VERSION}`, {rows[0]['draws']} simulated campaigns per scenario, 5 rounds each (seed {SEED}).",
        "",
        "| Scenario | Creative fatigue? | Engine alerts | Naive rule alerts | Engine's usual verdict |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['label']} | {'yes' if r['truth'] else 'no'} | {r['engine_alarm']:.0%} | {r['naive_alarm']:.0%} | `{r['top_status']}` |")
    false = [r for r in rows if not r["truth"]]
    lines += ["", f"Across the scenarios without creative fatigue the engine alerted in "
              f"{sum(r['engine_alarm'] for r in false) / len(false):.1%} of campaigns, the naive rule in "
              f"{sum(r['naive_alarm'] for r in false) / len(false):.0%}. With enough people per round it caught "
              f"{next(r for r in rows if r['key'] == 'worn_out')['engine_alarm']:.0%} of worn-out concepts; on 60-person lists and on "
              "social channels it says the data can't tell, by design."]
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
