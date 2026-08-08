import os
from functools import lru_cache

from supabase import Client, create_client

from src.capabilities.audience import Persona


@lru_cache(maxsize=1)
def get_client() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def create_campaign(
    idea: str,
    domain_category: str,
    feasibility_score: int,
    feasibility_rationale: str,
    *,
    reddit_subreddit: str | None = None,
    email_to: list[str] | None = None,
    cta_url: str | None = None,
) -> str:
    row = {
        "idea": idea,
        "domain_category": domain_category,
        "feasibility_score": feasibility_score,
        "feasibility_rationale": feasibility_rationale,
        "reddit_subreddit": reddit_subreddit,
        "email_to": email_to,
        "cta_url": cta_url,
        "status": "awaiting_gate_1",
    }
    result = get_client().table("campaigns").insert(row).execute()
    return result.data[0]["id"]


def get_campaign(campaign_id: str) -> dict:
    result = get_client().table("campaigns").select("*").eq("id", campaign_id).single().execute()
    return result.data


def update_campaign_status(campaign_id: str, status: str) -> None:
    get_client().table("campaigns").update({"status": status}).eq("id", campaign_id).execute()


def insert_personas(campaign_id: str, personas: list[Persona], *, primary_index: int = 0) -> None:
    rows = [
        {**p.model_dump(), "campaign_id": campaign_id, "is_primary": i == primary_index}
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


def create_pending_gate(campaign_id: str, gate_number: int, round_number: int = 1) -> None:
    row = {"campaign_id": campaign_id, "gate_number": gate_number, "round_number": round_number}
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


def upsert_iteration(campaign_id: str, round_number: int, **fields) -> None:
    row = {"campaign_id": campaign_id, "round_number": round_number, **fields}
    get_client().table("iterations").upsert(row, on_conflict="campaign_id,round_number").execute()
