import os
from functools import lru_cache

from supabase import Client, create_client

from src.capabilities.audience import Persona


@lru_cache(maxsize=1)
def get_client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def create_campaign(
    campaign_id: str,
    user_id: str,
    idea: str,
    domain_category: str,
    feasibility_score: int,
    feasibility_rationale: str,
    *,
    reddit_subreddit: str | None = None,
    email_to: list[str] | None = None,
    cta_url: str | None = None,
    use_image_template: bool = False,
    use_email_template: bool = False,
    max_rounds: int | None = None,
    max_duration_minutes: int | None = None,
    target_language: str = "en",
) -> None:
    row = {
        "id": campaign_id,
        "user_id": user_id,
        "idea": idea,
        "domain_category": domain_category,
        "feasibility_score": feasibility_score,
        "feasibility_rationale": feasibility_rationale,
        "reddit_subreddit": reddit_subreddit,
        "email_to": email_to,
        "cta_url": cta_url,
        "use_image_template": use_image_template,
        "use_email_template": use_email_template,
        "max_rounds": max_rounds,
        "max_duration_minutes": max_duration_minutes,
        "target_language": target_language,
        "status": "created",
    }
    get_client().table("campaigns").insert(row).execute()


def get_campaign(campaign_id: str) -> dict:
    result = get_client().table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


def update_campaign_status(campaign_id: str, status: str) -> None:
    get_client().table("campaigns").update({"status": status}).eq("id", campaign_id).execute()


def insert_personas(campaign_id: str, user_id: str, personas: list[Persona], *, primary_index: int = 0) -> None:
    rows = [
        {**p.model_dump(), "campaign_id": campaign_id, "user_id": user_id, "is_primary": i == primary_index}
        for i, p in enumerate(personas)
    ]
    get_client().table("personas").insert(rows).execute()


def get_personas(campaign_id: str) -> list[dict]:
    result = get_client().table("personas").select("*").eq("campaign_id", campaign_id).execute()
    return result.data


def get_primary_persona(campaign_id: str) -> dict:
    result = (
        get_client()
        .table("personas")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("is_primary", True)
        .single()
        .execute()
    )
    return result.data


def create_pending_gate(campaign_id: str, user_id: str, gate_number: int, round_number: int = 1) -> None:
    row = {
        "campaign_id": campaign_id,
        "user_id": user_id,
        "gate_number": gate_number,
        "round_number": round_number,
    }
    get_client().table("gate_decisions").upsert(row, on_conflict="campaign_id,gate_number,round_number").execute()


def get_gate_decision(campaign_id: str, gate_number: int, round_number: int = 1) -> dict | None:
    result = (
        get_client()
        .table("gate_decisions")
        .select("*")
        .eq("campaign_id", campaign_id)
        .eq("gate_number", gate_number)
        .eq("round_number", round_number)
        .maybe_single()
        .execute()
    )
    return result.data if result else None


def upsert_iteration(campaign_id: str, user_id: str, round_number: int, **fields) -> None:
    row = {"campaign_id": campaign_id, "user_id": user_id, "round_number": round_number, **fields}
    get_client().table("iterations").upsert(row, on_conflict="campaign_id,round_number").execute()


def get_template(user_id: str, template_type: str) -> dict | None:
    result = (
        get_client()
        .table("templates")
        .select("*")
        .eq("user_id", user_id)
        .eq("template_type", template_type)
        .maybe_single()
        .execute()
    )
    return result.data if result else None


def set_template(user_id: str, template_type: str, **fields) -> None:
    row = {"user_id": user_id, "template_type": template_type, **fields}
    get_client().table("templates").upsert(row, on_conflict="user_id,template_type").execute()


def update_campaign(campaign_id: str, **fields) -> None:
    get_client().table("campaigns").update(fields).eq("id", campaign_id).execute()


def get_iteration(campaign_id: str, round_number: int) -> dict | None:
    result = (
        get_client().table("iterations").select("*")
        .eq("campaign_id", campaign_id).eq("round_number", round_number)
        .maybe_single().execute()
    )
    return result.data if result else None


def get_all_iterations(campaign_id: str) -> list[dict]:
    result = get_client().table("iterations").select("*").eq("campaign_id", campaign_id).order("round_number").execute()
    return result.data


def upsert_metric(campaign_id: str, user_id: str, round_number: int, channel: str, raw_metrics: dict, reward: float) -> None:
    row = {"campaign_id": campaign_id, "user_id": user_id, "round_number": round_number,
           "channel": channel, "raw_metrics": raw_metrics, "reward": reward}
    get_client().table("metrics").upsert(row, on_conflict="campaign_id,round_number,channel").execute()


def get_all_metrics(campaign_id: str) -> list[dict]:
    result = get_client().table("metrics").select("*").eq("campaign_id", campaign_id).order("round_number").execute()
    return result.data


def get_click_count(campaign_id: str, round_number: int) -> int:
    result = (
        get_client().table("click_log").select("id", count="exact")
        .eq("campaign_id", campaign_id).eq("round_id", round_number).eq("channel", "email")
        .execute()
    )
    return result.count or 0


def insert_feedback(campaign_id, user_id, round_number, *, overall_reward, stakeholder_comment, revision_directive, continued) -> None:
    row = {"campaign_id": campaign_id, "user_id": user_id, "round_number": round_number,
           "overall_reward": overall_reward, "stakeholder_comment": stakeholder_comment,
           "revision_directive": revision_directive, "continued": continued}
    get_client().table("feedback").insert(row).execute()
