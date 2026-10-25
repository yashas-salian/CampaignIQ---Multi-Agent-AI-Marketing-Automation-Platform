"""Benchmark the crash test's rule checks on a fixed set of ads.

    python -m src.eval.crashtest_benchmark          # print the table
    python -m src.eval.crashtest_benchmark --write  # also update docs/CRASH_TEST.md

Each case is a short ad with one planted problem (or none) of a known type,
written in the patterns real ads get flagged for. Reported:
  * detection: planted problems the rule checks catch, overall and per type;
  * false alarms: high/critical findings on clean ads;
  * the old guardrails alone (brand-safety checks before the crash test) on
    the same ads, as the baseline;
  * reproducibility: every case run twice gives identical findings.
The simulated scenarios aren't benchmarked here: they need an LLM and their
output varies by design. They're labelled "simulation" everywhere.
"""
import sys
from pathlib import Path

from src.capabilities.crash_test import RULES_VERSION, AdText, rule_checks
from src.capabilities.guardrails import check_creative

DOC = Path(__file__).resolve().parents[2] / "docs" / "CRASH_TEST.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"

IDEA = "Order-ahead coffee app for metro commuters. First order free."

# (id, planted type or None, body, headline, cta, domain)
CASES = [
    ("named_testimonial", "INVENTED_TESTIMONIAL", "Priya says it changed her mornings. Order ahead and skip the queue.", "", "", "other"),
    ("quote_attribution", "INVENTED_TESTIMONIAL", '"Best coffee app I have ever used" - Arjun. Try it today.', "", "", "other"),
    ("star_rating", "INVENTED_TESTIMONIAL", "Rated 4.9 out of 5 by commuters. Your coffee, ready when you arrive.", "", "", "other"),
    ("happy_customers", "INVENTED_TESTIMONIAL", "Thousands of happy customers skip the line every day.", "", "", "other"),
    ("people_joined", "FAKE_SOCIAL_PROOF", "12,000 commuters already joined. Order ahead now.", "", "", "other"),
    ("bestseller", "FAKE_SOCIAL_PROOF", "The best-selling coffee app on the metro. First order free.", "", "", "other"),
    ("trusted_by", "FAKE_SOCIAL_PROOF", "Trusted by thousands of commuters every morning.", "", "", "other"),
    ("limited_time", "FALSE_URGENCY", "Limited time: your first order is free. Order ahead today.", "", "", "other"),
    ("spots_run_out", "FALSE_URGENCY", "Grab your free first order before the early-bird spots run out.", "", "", "other"),
    ("only_left", "FALSE_URGENCY", "Only 3 free coffees left for today. Order now.", "", "", "other"),
    ("ends_tonight", "FALSE_URGENCY", "Offer ends tonight. Skip the queue tomorrow.", "Hurry, offer ends tonight", "", "other"),
    ("debt_question", "PERSONAL_ATTRIBUTE", "Are you struggling with debt? Save on coffee with our app.", "", "", "finance_fintech"),
    ("weight_question", "PERSONAL_ATTRIBUTE", "Are you overweight? Try our sugar-free coffee.", "", "", "fitness_wellness"),
    ("your_condition", "PERSONAL_ATTRIBUTE", "Coffee made for your condition, ready when you arrive.", "", "", "healthcare"),
    ("invented_percent", "UNVERIFIED_NUMBER", "Save 40% on every coffee you order ahead.", "", "", "other"),
    ("invented_minutes", "UNVERIFIED_NUMBER", "Your coffee ready in 2 minutes, every time.", "", "", "other"),
    ("price", "UNVERIFIED_NUMBER", "Coffee from ₹49, ready when you step off the metro.", "", "", "other"),
    ("guaranteed", "UNSUPPORTED_CLAIM", "Guaranteed the best coffee on your commute.", "", "", "other"),
    ("cure_claim", "UNSUPPORTED_CLAIM", "Our tea cures headaches on the way to work.", "", "", "healthcare"),
    ("foreign_link", "POLICY_VIOLATION", "Order now at cheapcoffee.xyz and skip the queue.", "", "", "other"),
    ("phone_number", "POLICY_VIOLATION", "Call +91 98765 43210 to order your coffee ahead.", "", "", "other"),
    ("headline_link", "POLICY_VIOLATION", "Skip the queue every morning.", "Visit coffeehub.io now", "", "other"),
    ("clean_1", None, "Step off the metro and your coffee is already waiting. First order free.", "Coffee ready when you are", "Order now", "other"),
    ("clean_2", None, "Order on the train, pick up at the station. No queue, no waiting around.", "Skip the queue", "Get the app", "other"),
    ("clean_3", None, "Your usual, made just before you arrive. First order is on us.", "Your usual, on time", "Order ahead", "other"),
    ("clean_4", None, "She says mornings are calmer now? We think yours could be too: order ahead and pick up.", "", "Try it", "other"),
    ("clean_5", None, "Fresh coffee, timed to your commute. First order free.", "Timed to your train", "Start now", "other"),
    ("clean_6", None, "Pick a drink, pick a station, and it is ready when you get there.", "Ready at your station", "Order", "other"),
]


def _types(findings, severities=("medium", "high", "critical")) -> set[str]:
    return {f.type for f in findings if f.severity in severities}


def _baseline_hit(planted: str, body: str, headline: str, domain: str) -> bool:
    """Would the old brand-safety checks have flagged this ad at all (block or review)?"""
    g = check_creative(body, domain_category=domain)
    gh = check_creative(headline, domain_category=domain) if headline else None
    flagged = any(i.severity == "block" or i.category == "claims" for i in g.issues)
    flagged = flagged or bool(gh and gh.blocked)
    return flagged


def run() -> dict:
    rows = []
    for cid, planted, body, headline, cta, domain in CASES:
        ad = AdText(body=body, headline=headline, cta=cta)
        first = rule_checks(ad, idea=IDEA, domain_category=domain)
        second = rule_checks(ad, idea=IDEA, domain_category=domain)
        rows.append({
            "id": cid, "planted": planted, "found": sorted(_types(first)),
            "hit": planted in _types(first) if planted else None,
            "false_alarm": bool(_types(first, ("high", "critical"))) if planted is None else None,
            "baseline_hit": _baseline_hit(planted, body, headline, domain) if planted else None,
            "reproducible": [f.model_dump() for f in first] == [f.model_dump() for f in second],
        })
    planted = [r for r in rows if r["planted"]]
    clean = [r for r in rows if not r["planted"]]
    by_type: dict[str, list[bool]] = {}
    for r in planted:
        by_type.setdefault(r["planted"], []).append(r["hit"])
    return {
        "rules_version": RULES_VERSION,
        "cases": len(rows),
        "planted": len(planted),
        "detected": sum(r["hit"] for r in planted),
        "baseline_detected": sum(r["baseline_hit"] for r in planted),
        "clean": len(clean),
        "false_alarms": sum(r["false_alarm"] for r in clean),
        "by_type": {t: (sum(v), len(v)) for t, v in by_type.items()},
        "reproducible": all(r["reproducible"] for r in rows),
        "rows": rows,
    }


def markdown(result: dict) -> str:
    lines = [
        f"Rules `{result['rules_version']}`, {result['cases']} ads ({result['planted']} with one planted problem, "
        f"{result['clean']} clean) - `python -m src.eval.crashtest_benchmark`.",
        "",
        "| | Crash-test rule checks | Brand-safety checks alone (before) |",
        "|---|---|---|",
        f"| Planted problems caught | **{result['detected']} / {result['planted']}** | {result['baseline_detected']} / {result['planted']} |",
        f"| False alarms (high/critical) on clean ads | **{result['false_alarms']} / {result['clean']}** | - |",
        f"| Same findings on re-run | {'yes' if result['reproducible'] else 'NO'} | yes |",
        "",
        "| Problem type | Caught |",
        "|---|---|",
    ]
    for t, (hit, total) in sorted(result["by_type"].items()):
        lines.append(f"| {t} | {hit} / {total} |")
    return "\n".join(lines)


def main() -> None:
    result = run()
    table = markdown(result)
    print(table)
    misses = [r for r in result["rows"] if r["hit"] is False or r["false_alarm"]]
    for r in misses:
        print(f"  miss/false alarm: {r['id']} planted={r['planted']} found={r['found']}")
    if "--write" in sys.argv:
        text = DOC.read_text(encoding="utf-8")
        head, rest = text.split(START, 1)
        tail = rest.split(END, 1)[1]
        DOC.write_text(f"{head}{START}\n{table}\n{END}{tail}", encoding="utf-8")
        print(f"\nwrote {DOC}")


if __name__ == "__main__":
    main()
