"""Benchmark competitor intelligence: the forecast on held-out history, and the
signal pipeline on labelled headlines.

    python -m src.eval.competitor_benchmark          # print the tables
    python -m src.eval.competitor_benchmark --write  # also update docs/COMPETITOR_INTELLIGENCE.md

1. Forecast (model trend-v1). Data: five years of weekly Google Trends
   interest for 12 category keywords (src/eval/data/trends_weekly.json, fetched
   once and stored, so the result is reproducible and no test calls Google).
   The model's two weights and the interval's widening factor were chosen on
   the first three years (origins in weeks 60-156); everything reported below
   is on the later, held-out weeks only. Target: the change in mean interest
   over the next two weeks against the last four. Compared with the naive
   forecast "no change". Reported: mean absolute error, 80% interval coverage,
   and for "a rise of 10%+" calls, how often the rise happened.

2. Signals. 24 headlines about three made-up competitors: rewrites and
   syndicated copies of the same stories, articles that only mention the
   name in passing, and coverage that isn't a move at all. Reported: how
   many independent stories the engine counts against the truth (and against
   counting articles), the move-type accuracy, and false events.
"""
import json
import statistics
import sys
from pathlib import Path

from src.capabilities.competitors import (
    FORECAST_MODEL, HORIZON_WEEKS, OPPORTUNITY_RISE, assign_stories, forecast_change, forecast_interval, news_events,
    observed_change,
)

DATA = Path(__file__).with_name("data") / "trends_weekly.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "COMPETITOR_INTELLIGENCE.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
TUNE_END = 157  # origins before this week fitted the model; from here on it's held out


def forecast_backtest() -> dict:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    rows = {"tune": [], "test": []}
    for keyword, s in data["series"].items():
        v = [float(x) for x in s["values"]]
        for t in range(60, len(v) - HORIZON_WEEKS + 1):
            f = forecast_change(v, t)
            band = forecast_interval(v, t) if f else None
            actual = observed_change(v, t)
            if not f or not band or actual is None:
                continue
            rows["tune" if t < TUNE_END else "test"].append({
                "keyword": keyword, "pred": f[0], "low": f[0] + band[0], "high": f[0] + band[1], "actual": actual,
            })
    out = {"source": data["source"], "fetched_at": data["fetched_at"], "keywords": len(data["series"])}
    for split, r in rows.items():
        calls = [x for x in r if x["pred"] >= OPPORTUNITY_RISE]
        rises = [x for x in r if x["actual"] >= OPPORTUNITY_RISE]
        out[split] = {
            "forecasts": len(r),
            "model_mae": statistics.mean(abs(x["actual"] - x["pred"]) for x in r),
            "naive_mae": statistics.mean(abs(x["actual"]) for x in r),
            "coverage": sum(x["low"] <= x["actual"] <= x["high"] for x in r) / len(r),
            "rise_calls": len(calls),
            "rise_precision": (sum(x["actual"] >= OPPORTUNITY_RISE for x in calls) / len(calls)) if calls else None,
            "rise_recall": (sum(x["pred"] >= OPPORTUNITY_RISE for x in rises) / len(rises)) if rises else None,
        }
    return out


# (outlet, title, description, true story id or None if not a move, true kind or None)
HEADLINES = [
    ("Reuters", "BrewCo launches cold brew subscription for commuters", "The coffee chain unveiled a monthly plan.", "s1", "PRODUCT_LAUNCH"),
    ("Yahoo Finance", "BrewCo launches cold brew subscription for commuters - Reuters", "The coffee chain unveiled a monthly plan.", "s1", "PRODUCT_LAUNCH"),
    ("MarketWatch", "BrewCo launches cold-brew subscription aimed at commuters", "Syndicated from Reuters.", "s1", "PRODUCT_LAUNCH"),
    ("The Verge", "BrewCo's new cold brew subscription targets commuters", "BrewCo rolls out a subscription.", "s1", "PRODUCT_LAUNCH"),
    ("Food Dive", "BrewCo slashes prices on iced drinks by 30% for summer", "A summer discount across stores.", "s2", "OFFER_CHANGE"),
    ("Business Insider", "BrewCo slashes iced drink prices 30% for the summer", "", "s2", "OFFER_CHANGE"),
    ("CNBC", "BrewCo cuts prices on iced drinks by 30% this summer", "", "s2", "OFFER_CHANGE"),
    ("AdAge", "BrewCo rebrand drops 'coffee' from its name in new ad campaign", "", "s3", "MESSAGING_SHIFT"),
    ("Campaign", "BrewCo rebrands, drops 'coffee' from name in ad campaign", "", "s3", "MESSAGING_SHIFT"),
    ("Bloomberg", "Coffee prices hit a 10-year high; BrewCo among chains watching costs", "Commodity markets.", None, None),
    ("Eater", "The 10 best coffee shops in Austin", "Including one BrewCo location.", None, None),
    ("TechCrunch", "MealBox unveils a new vegan line", "The meal-kit company debuts plant-based boxes.", "s4", "PRODUCT_LAUNCH"),
    ("The Spoon", "MealBox unveils new vegan meal line", "", "s4", "PRODUCT_LAUNCH"),
    ("Retail Dive", "MealBox offers first box free to new subscribers", "A promotion through March.", "s5", "OFFER_CHANGE"),
    ("PR Newswire", "MealBox offers first box free for new subscribers", "", "s5", "OFFER_CHANGE"),
    ("Forbes", "MealBox CEO on profitability and the meal-kit market", "An interview.", None, None),
    ("Axios", "Meal kits are back: MealBox, HelloFresh and others report growth", "", None, None),
    ("Wired", "StrideRun debuts a carbon-plated trainer", "The running brand's new model.", "s6", "PRODUCT_LAUNCH"),
    ("Runner's World", "StrideRun debuts carbon-plated trainer for racers", "", "s6", "PRODUCT_LAUNCH"),
    ("Engadget", "StrideRun debuts a carbon-plated trainer - Wired", "", "s6", "PRODUCT_LAUNCH"),
    ("Sports Business", "StrideRun's new tagline: 'Every runner, every road'", "A new campaign.", "s7", "MESSAGING_SHIFT"),
    ("Outside", "Stride and run: our favourite trails this autumn", "No brand news.", None, None),
    ("Footwear News", "StrideRun price increase on flagship shoes", "", "s8", "OFFER_CHANGE"),
    ("Gear Patrol", "Best running shoes of the year, including StrideRun", "A review roundup.", None, None),
]
NAMES = {"BrewCo": ["BrewCo"], "MealBox": ["MealBox"], "StrideRun": ["StrideRun"]}


def signal_check() -> dict:
    articles_total = stories_true = stories_found = right_kind = moves = false_events = 0
    split = merged = 0
    for company, names in NAMES.items():
        rows = [h for h in HEADLINES if h[1].startswith(company) or company in h[1]]
        articles = [{"title": t, "description": d, "url": f"https://news.example/{i}", "outlet": o, "published_at": None}
                    for i, (o, t, d, _, _) in enumerate(rows)]
        truth = {a["title"]: (story, kind) for a, (_, _, _, story, kind) in zip(articles, rows)}
        events = assign_stories(news_events(articles, names), [])
        articles_total += sum(1 for _, _, _, story, _ in rows if story)
        stories_true += len({story for _, _, _, story, _ in rows if story})
        stories_found += len({e.story_key for e in events})
        by_story: dict[str, set] = {}
        for e in events:
            story, kind = truth[e.title]
            if story is None:
                false_events += 1
                continue
            moves += 1
            right_kind += e.kind == kind
            by_story.setdefault(story, set()).add(e.story_key)
        keys_to_stories: dict[str, set] = {}
        for e in events:
            if truth[e.title][0]:
                keys_to_stories.setdefault(e.story_key, set()).add(truth[e.title][0])
        split += sum(len(k) - 1 for k in by_story.values())       # one story counted as several
        merged += sum(len(s) - 1 for s in keys_to_stories.values())  # several stories counted as one
    return {"headlines": len(HEADLINES), "move_articles": articles_total, "true_stories": stories_true,
            "stories_found": stories_found, "kind_accuracy": right_kind / moves if moves else 0.0,
            "false_events": false_events, "split": split, "merged": merged}


def run() -> dict:
    return {"forecast": forecast_backtest(), "signals": signal_check()}


def table(r: dict) -> str:
    f, s = r["forecast"], r["signals"]
    pct = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
    rel = lambda x: f"{x * 100:.1f}%"  # noqa: E731  (errors in relative change: 0.149 = 14.9% of the base level)
    lines = [
        f"**Forecast `{FORECAST_MODEL}`**: {f['keywords']} category keywords, {f['source']} (fetched {f['fetched_at'][:10]}). "
        "Weights chosen on the first three years; the held-out column is the later weeks only.",
        "",
        "| | Fitting years | Held-out years |",
        "|---|---|---|",
        f"| Forecasts | {f['tune']['forecasts']} | {f['test']['forecasts']} |",
        f"| Mean absolute error of the change, model | {rel(f['tune']['model_mae'])} | {rel(f['test']['model_mae'])} |",
        f"| Mean absolute error of the change, naive \"no change\" | {rel(f['tune']['naive_mae'])} | {rel(f['test']['naive_mae'])} |",
        f"| 80% interval contained the outcome | {pct(f['tune']['coverage'])} | {pct(f['test']['coverage'])} |",
        f"| \"Rise of 10%+\" calls | {f['tune']['rise_calls']} | {f['test']['rise_calls']} |",
        f"| … that came true | {pct(f['tune']['rise_precision'])} | {pct(f['test']['rise_precision'])} |",
        f"| Rises of 10%+ that were called | {pct(f['tune']['rise_recall'])} | {pct(f['test']['rise_recall'])} |",
        "",
        f"**Signals**: {s['headlines']} labelled headlines about 3 competitors.",
        "",
        "| | Result |",
        "|---|---|",
        f"| Reports of real moves | {s['move_articles']} articles |",
        f"| Independent stories (truth) | {s['true_stories']} |",
        f"| Stories the engine counted | {s['stories_found']} |",
        f"| One story counted twice / two stories merged | {s['split']} / {s['merged']} |",
        f"| Move type right | {pct(s['kind_accuracy'])} |",
        f"| Events from articles that weren't a move | {s['false_events']} |",
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
