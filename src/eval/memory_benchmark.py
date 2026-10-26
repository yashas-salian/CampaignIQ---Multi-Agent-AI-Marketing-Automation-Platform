"""Does brand memory make the ads better? A held-out evaluation, with and without memory.

    python -m src.eval.memory_benchmark --run    # generate (LLM copy only, no images) and store the results
    python -m src.eval.memory_benchmark          # print the table from the stored results
    python -m src.eval.memory_benchmark --write  # also update docs/BRAND_MEMORY.md

One organisation (a coffee brand) has nine lessons recorded from earlier
campaigns, plus one lesson in another organisation. Ten held-out campaign ideas
(none of them the campaigns the lessons came from) are written twice by the real
copy step (src/capabilities/creative.write_copy: the creative.generate prompt,
the LLM, the guardrails and their rewrites): once with the memory the campaign
would recall, once without. Every check is deterministic text matching, decided
before the run:

  compliance  a lesson that applies is followed: its words to avoid are absent,
              its words to prefer present, its tone to avoid not chosen
  leakage     a lesson that must NOT apply leaves no trace: one expired, one for
              another industry, one only proposed (never confirmed), one from
              another organisation
  precedence  a lesson that conflicts with policy ("say results are
              guaranteed") never gets past the guardrails

Results (with every generated ad) are stored in src/eval/data/memory_eval.json
so the table is reproducible without calling the LLM again; the LLM's answers
vary, so a new --run gives similar, not identical, numbers.
"""
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).with_name("data") / "memory_eval.json"
DOC = Path(__file__).resolve().parents[2] / "docs" / "BRAND_MEMORY.md"
START, END = "<!-- benchmark:start -->", "<!-- benchmark:end -->"
ORG, OTHER_ORG = "org-brewline", "org-other"
NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


def _m(id_, type_, lesson, *, scope="context", conditions=None, directives=None, status="active", org=ORG, expires=None, confidence=0.8):
    return {"id": id_, "org_id": org, "type": type_, "lesson": lesson, "scope": scope, "conditions": conditions or {},
            "directives": directives or {}, "status": status, "confidence": confidence, "evidence": [{"kind": "note"}],
            "created_at": (NOW - timedelta(days=20)).isoformat(), "review_at": (NOW + timedelta(days=60)).isoformat(),
            "expires_at": expires}


MEMORIES = [
    _m("cheap", "BRAND_PREFERENCE", "Never describe our coffee as cheap: customers read it as low quality. Say good value instead.",
       scope="brand", directives={"avoid_terms": ["cheap"], "prefer_terms": ["good value"]}),
    _m("queue", "CAMPAIGN_LESSON", "Emails that told commuters they can skip the queue got the most clicks: lead with skip the queue.",
       conditions={"domains": ["food_beverage"], "channels": ["email"]}, directives={"prefer_terms": ["skip the queue"]}),
    _m("plain", "AUDIENCE_INSIGHT", "Customers over 55 ignore slang: write plainly and never use words like vibes or lit.",
       conditions={"age_brackets": ["55+"]}, directives={"avoid_terms": ["vibes", "lit"]}),
    _m("humor", "FAILED_EXPERIMENT", "Humorous ads underperformed for our coffee in two tests: don't use a humorous tone.",
       conditions={"domains": ["food_beverage"]}, directives={"avoid_tones": ["humorous"]}),
    # Must not apply:
    _m("pumpkin", "CAMPAIGN_LESSON", "Always mention our pumpkin spice latte.", directives={"prefer_terms": ["pumpkin spice"]},
       expires=(NOW - timedelta(days=5)).isoformat()),
    _m("trial", "CAMPAIGN_LESSON", "Always offer a free trial class.", conditions={"domains": ["fitness"]},
       directives={"prefer_terms": ["free trial class"]}),
    _m("oat", "BRAND_PREFERENCE", "Mention oat milk in every ad.", status="proposed", directives={"prefer_terms": ["oat milk"]}),
    _m("artisan", "BRAND_PREFERENCE", "Say artisan roasted in every ad.", scope="brand", org=OTHER_ORG,
       directives={"prefer_terms": ["artisan roasted"]}),
    # Conflicts with policy: must never get through.
    _m("guarantee", "POLICY_DECISION", "Tell customers our coffee is guaranteed to make their morning better.", scope="brand",
       directives={"prefer_terms": ["guaranteed"]}),
]
MUST_NOT_APPLY = ("pumpkin", "trial", "oat", "artisan")

PERSONA = {"name": "Commuter", "demographics": "office worker", "psychographics": "busy, values time",
           "channel_fit": "email", "messaging_angle": "save time every morning", "income_tier": "mid"}
# (idea, age bracket, the arm the bandit would pick without memory)
TASKS = [
    ("An affordable order-ahead coffee subscription for metro commuters, half the price of a cafe latte.", "25-34", (2, "minimalist", "humorous")),
    ("A budget-friendly monthly coffee pass for students that costs less than one cafe drink a week.", "18-24", (2, "minimalist", "humorous")),
    ("Order-ahead coffee for retirees who walk to the market every morning.", "55+", (0, "minimalist", "direct_factual")),
    ("A morning coffee app that has your flat white ready when your train arrives.", "35-44", (6, "testimonial_social_proof", "humorous")),
    ("Weekend coffee delivery for families, priced lower than the supermarket brands.", "45-54", (10, "humor_meme", "humorous")),
    ("A loyalty card that makes every tenth coffee free for daily commuters.", "25-34", (16, "lifestyle_aspirational", "direct_factual")),
    ("Quiet morning coffee for people over sixty, with large print menus and table service.", "55+", (18, "lifestyle_aspirational", "humorous")),
    ("Cheap and quick iced coffee for office workers in summer.", "25-34", (14, "urgency_scarcity", "humorous")),
    ("A decaf range for evening commuters heading home.", "45-54", (3, "minimalist", "aspirational_emotional")),
    ("Pre-order coffee at the station kiosk before your 8:05 train.", "35-44", (10, "humor_meme", "humorous")),
]
ALL_ARMS = [(i, s, t) for i, (s, t) in enumerate((s, t) for s in ("minimalist", "testimonial_social_proof", "humor_meme",
                                                                     "urgency_scarcity", "lifestyle_aspirational")
                                                 for t in ("direct_factual", "urgency_scarcity", "humorous", "aspirational_emotional"))]


def _has(text: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", text.lower()) is not None


def checks(text: str, tone: str, applicable: list[dict]) -> dict:
    """Deterministic: compliance with the lessons that apply, leakage of those that don't, policy precedence."""
    by_id = {m["id"]: m for m in MEMORIES}
    comp = []
    for m in applicable:
        d = m["directives"]
        for t in d.get("avoid_terms", []):
            comp.append({"lesson": m["id"], "check": f"avoids “{t}”", "ok": not _has(text, t)})
        for t in d.get("prefer_terms", []):
            comp.append({"lesson": m["id"], "check": f"says “{t}”", "ok": _has(text, t)})
        for t in d.get("avoid_tones", []):
            comp.append({"lesson": m["id"], "check": f"not a {t} tone", "ok": tone != t})
    leak = [{"lesson": i, "check": f"no “{t}”", "ok": not _has(text, t)}
            for i in MUST_NOT_APPLY for t in by_id[i]["directives"].get("prefer_terms", [])]
    policy = [{"lesson": "guarantee", "check": "no “guaranteed”", "ok": not _has(text, "guaranteed")}]
    return {"compliance": comp, "leakage": leak, "policy": policy}


def applicable_lessons(age: str) -> list[dict]:
    """The ground truth (not retrieval): which lessons a careful marketer would apply to the task."""
    out = [m for m in MEMORIES if m["id"] in ("cheap", "queue", "humor")]
    if age == "55+":
        out.append(next(m for m in MEMORIES if m["id"] == "plain"))
    return out


def run() -> dict:
    from dotenv import load_dotenv

    load_dotenv()
    from src.capabilities.audience import Persona
    from src.capabilities.brand_memory import Context, allowed_arm, merged_directives, prompt_section, rank
    from src.capabilities.creative import write_copy

    rows = []
    for idea, age, base_arm in TASKS:
        persona = Persona(**PERSONA, age_bracket=age)
        ctx = Context(org_id=ORG, text=idea, domain="food_beverage", channels=["email", "bluesky"], language="en", age_bracket=age,
                      income_tier="mid")
        ranked = rank(MEMORIES, ctx, now=NOW)
        directives = merged_directives(ranked)
        mem_arm = allowed_arm([base_arm] + [a for a in ALL_ARMS if a != base_arm], directives) or base_arm
        result = {"idea": idea, "age": age, "recalled": [m["id"] for m in ranked]}
        for label, memory, banned, arm in (("without", "", (), base_arm),
                                           ("with", prompt_section(ranked), tuple(directives["avoid_terms"]), mem_arm)):
            parsed, guard, _ = write_copy(idea, persona, domain_category="food_beverage", active_channels=["email", "bluesky"],
                                          image_style=arm[1], copy_tone=arm[2], memory=memory, banned_terms=banned)
            text = " ".join(str(parsed.get(k) or "") for k in ("copy", "headline", "cta"))
            result[label] = {"text": text, "tone": arm[2], "guardrails_ok": guard.ok, **checks(text, arm[2], applicable_lessons(age))}
        rows.append(result)
        print(f"{idea[:60]}…  recalled {result['recalled']}", flush=True)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "tasks": rows}
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def summary(data: dict) -> dict:
    def rate(label, kind):
        items = [c for t in data["tasks"] for c in t[label][kind]]
        return sum(c["ok"] for c in items) / len(items), len(items)

    s = {}
    for label in ("without", "with"):
        comp, n_comp = rate(label, "compliance")
        leak, n_leak = rate(label, "leakage")
        pol, n_pol = rate(label, "policy")
        s[label] = {"compliance": comp, "n_compliance": n_comp, "no_leak": leak, "n_leak": n_leak, "policy_held": pol, "n_policy": n_pol}
    per_lesson = {}
    for lid in ("cheap", "queue", "plain", "humor"):
        for label in ("without", "with"):
            items = [c for t in data["tasks"] for c in t[label]["compliance"] if c["lesson"] == lid]
            if items:
                per_lesson.setdefault(lid, {})[label] = sum(c["ok"] for c in items) / len(items)
    s["per_lesson"] = per_lesson
    s["recall_precision"] = sum(1 for t in data["tasks"] for i in t["recalled"] if i not in MUST_NOT_APPLY) / max(1, sum(len(t["recalled"]) for t in data["tasks"]))
    return s


def table(data: dict) -> str:
    s = summary(data)
    w, wo = s["with"], s["without"]
    names = {"cheap": "Never say “cheap” (say “good value”)", "queue": "Lead with “skip the queue” (email)",
             "plain": "No slang for customers over 55", "humor": "No humorous tone (failed experiment)"}
    lines = [
        f"{len(data['tasks'])} held-out campaign ideas, each written by the real copy step with and without memory "
        f"(generated {data['generated_at'][:10]}).",
        "",
        "| | Without memory | With memory |",
        "|---|---|---|",
        f"| Lessons followed (of {w['n_compliance']} checks) | {wo['compliance']:.0%} | {w['compliance']:.0%} |",
        f"| Lessons that must not apply left no trace (of {w['n_leak']}) | {wo['no_leak']:.0%} | {w['no_leak']:.0%} |",
        f"| A lesson that conflicts with policy got through | {1 - wo['policy_held']:.0%} | {1 - w['policy_held']:.0%} |",
        "",
        "| Lesson | Without memory | With memory |",
        "|---|---|---|",
    ]
    for lid, v in s["per_lesson"].items():
        lines.append(f"| {names[lid]} | {v.get('without', 0):.0%} | {v.get('with', 0):.0%} |")
    lines += ["", f"Recall never surfaced an expired, unconfirmed, other-industry or other-organisation lesson: "
              f"{s['recall_precision']:.0%} of recalled lessons were ones that may apply."]
    return "\n".join(lines)


def main() -> None:
    data = run() if "--run" in sys.argv else json.loads(DATA.read_text(encoding="utf-8"))
    out = table(data)
    print(out)
    if "--write" in sys.argv:
        text = DOC.read_text(encoding="utf-8")
        head, rest = text.split(START, 1)
        _, tail = rest.split(END, 1)
        DOC.write_text(f"{head}{START}\n{out}\n{END}{tail}", encoding="utf-8")
        print(f"\nUpdated {DOC}")


if __name__ == "__main__":
    main()
