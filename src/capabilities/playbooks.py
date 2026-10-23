"""Automatic playbooks: campaign memory turned into reusable written insight.

When a campaign finishes, its organisation's playbook for that industry is
rewritten from every measured round in that industry: which copy tones and
visual styles earned the most reward (computed, not guessed), plus the round
reviews and focus-group reactions, summarised by the LLM into do / avoid /
audience notes / next test. Later creatives in the industry are written with
the playbook in their prompt, so lessons carry over between campaigns.
Needs at least MIN_ROUNDS measured rounds; never raises into a campaign run.
"""
import logging
from datetime import datetime, timezone

from pydantic import BaseModel

from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence

log = logging.getLogger(__name__)

MIN_ROUNDS = 2


class PlaybookContent(BaseModel):
    headline: str
    do: list[str]
    avoid: list[str]
    audience: list[str]
    next_test: str


def _human(value: str) -> str:
    return value.replace("_", " ")


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def gather(org_id: str, domain_category: str) -> dict | None:
    """Every measured round of the org's campaigns in one industry, with stats."""
    from src.db.supabase_client import get_client

    client = get_client()
    campaigns = (
        client.table("campaigns").select("id,idea").eq("org_id", org_id).eq("domain_category", domain_category).execute().data
        or []
    )
    ids = [c["id"] for c in campaigns]
    if not ids:
        return None
    rounds = client.table("iterations").select(
        "campaign_id,round_number,copy_text,image_style,copy_tone,focus_group"
    ).in_("campaign_id", ids).execute().data or []
    metrics = client.table("metrics").select("campaign_id,round_number,reward").in_("campaign_id", ids).execute().data or []
    feedback = client.table("feedback").select("campaign_id,round_number,revision_directive").in_("campaign_id", ids).execute().data or []

    rewards: dict[tuple, list[float]] = {}
    for m in metrics:
        rewards.setdefault((m["campaign_id"], m["round_number"]), []).append(float(m["reward"]))
    measured = []
    for r in rounds:
        key = (r["campaign_id"], r["round_number"])
        if key in rewards and r.get("copy_tone") and r.get("image_style"):
            measured.append({**r, "reward": _mean(rewards[key])})
    if len(measured) < MIN_ROUNDS:
        return None

    def table(field: str) -> list[dict]:
        groups: dict[str, list[float]] = {}
        for r in measured:
            groups.setdefault(r[field], []).append(r["reward"])
        return sorted(({"name": k, "mean": _mean(v), "n": len(v)} for k, v in groups.items()), key=lambda g: -g["mean"])

    ranked = sorted(measured, key=lambda r: -r["reward"])
    notes = [
        str((f.get("revision_directive") or {}).get("reasoning", "")) for f in feedback
    ] + [
        q["quote"] for r in measured for q in ((r.get("focus_group") or {}).get("reactions") or []) if q.get("quote")
    ]
    return {
        "stats": {
            "rounds": len(measured),
            "campaigns": len({r["campaign_id"] for r in measured}),
            "overall_mean": _mean([r["reward"] for r in measured]),
            "tones": table("copy_tone"),
            "styles": table("image_style"),
        },
        "best": ranked[0],
        "worst": ranked[-1],
        "notes": [n for n in notes if n][:12],
    }


def write_playbook(org_id: str, domain_category: str, *, user_id: str | None = None, language: str = "en") -> dict | None:
    """Rewrite one playbook. Returns the saved row, or None when there's too little data."""
    data = gather(org_id, domain_category)
    if data is None:
        return None
    stats = data["stats"]
    stats_text = "\n".join(
        [f"Overall: mean reward {stats['overall_mean']} over {stats['rounds']} rounds in {stats['campaigns']} campaigns."]
        + [f"Copy tone {_human(g['name'])}: {g['mean']} (n={g['n']})" for g in stats["tones"]]
        + [f"Visual style {_human(g['name'])}: {g['mean']} (n={g['n']})" for g in stats["styles"]]
    )
    def describe(r: dict) -> str:
        return f"[reward {r['reward']}, {_human(r['copy_tone'])} copy, {_human(r['image_style'])} visual] {r.get('copy_text') or ''}"

    prompt, system = PROMPTS["playbook.write"].render(
        domain=_human(domain_category),
        stats=fence(stats_text, "results"),
        best=fence(describe(data["best"]), "ad_copy"),
        worst=fence(describe(data["worst"]), "ad_copy"),
        notes=fence("\n".join(f"- {n}" for n in data["notes"]) or "none", "notes"),
        language=language_name(language),
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)

    def strings(key: str, limit: int) -> list[str]:
        value = parsed.get(key) if isinstance(parsed, dict) else None
        items = value if isinstance(value, list) else [value] if value else []
        return [str(i).strip() for i in items if str(i).strip()][:limit]

    content = PlaybookContent(
        headline=str(parsed.get("headline", "")).strip() or f"{stats['rounds']} measured rounds so far.",
        do=strings("do", 4), avoid=strings("avoid", 3), audience=strings("audience", 3),
        next_test=str(parsed.get("next_test", "")).strip(),
    )
    from src.db.supabase_client import get_client

    row = {"org_id": org_id, "domain_category": domain_category, "content": content.model_dump(), "stats": stats,
           "generated_at": datetime.now(timezone.utc).isoformat()}
    saved = get_client().table("playbooks").upsert(row, on_conflict="org_id,domain_category").execute()
    return (saved.data or [row])[0]


def refresh_after_campaign(campaign_id: str, *, user_id: str | None = None) -> None:
    """Called when a campaign finishes: rewrite its industry's playbook. Never raises."""
    try:
        from src.db.supabase_client import get_client

        campaign = (
            get_client().table("campaigns").select("org_id,domain_category,target_language").eq("id", campaign_id)
            .maybe_single().execute()
        )
        if campaign and campaign.data and campaign.data.get("org_id"):
            write_playbook(campaign.data["org_id"], campaign.data["domain_category"], user_id=user_id,
                           language=campaign.data.get("target_language") or "en")
    except Exception as exc:
        log.warning("playbook refresh for %s failed: %s", campaign_id, exc)


def playbook_section_for_campaign(campaign_id: str | None) -> str:
    """The creative prompt's playbook section for this campaign's industry ("" if none). Never raises."""
    if not campaign_id:
        return ""
    try:
        from src.db.supabase_client import get_client

        client = get_client()
        campaign = client.table("campaigns").select("org_id,domain_category").eq("id", campaign_id).maybe_single().execute()
        if not campaign or not campaign.data or not campaign.data.get("org_id"):
            return ""
        row = (
            client.table("playbooks").select("content,stats").eq("org_id", campaign.data["org_id"])
            .eq("domain_category", campaign.data["domain_category"]).maybe_single().execute()
        )
        if not row or not row.data:
            return ""
        c = row.data["content"]
        lines = [f"Headline: {c.get('headline', '')}"] + [f"Do: {d}" for d in c.get("do", [])] + [f"Avoid: {a}" for a in c.get("avoid", [])]
        body = fence("\n".join(lines), "playbook")
        return (
            f"Proven playbook from this organisation's past campaigns in this industry "
            f"({row.data['stats'].get('rounds', 0)} measured rounds); follow it unless the required archetypes conflict:\n{body}\n"
        )
    except Exception as exc:
        log.warning("playbook lookup failed for %s: %s", campaign_id, exc)
        return ""
