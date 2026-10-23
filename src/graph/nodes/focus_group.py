import logging

from src.capabilities.audience import Persona
from src.capabilities.focus_group import run_focus_group
from src.db.supabase_client import get_personas, upsert_iteration
from src.graph.state import CampaignState

log = logging.getLogger(__name__)


def focus_group_node(state: CampaignState) -> CampaignState:
    """All of the campaign's personas react to the final draft before Gate 2.

    Advice for the approver only: any failure (LLM down, budget spent) skips it
    and the campaign carries on to the gate unchanged."""
    try:
        rows = get_personas(state["campaign_id"])
        # Primary first, so the panel reads in the same order as the persona cards.
        rows.sort(key=lambda r: not r.get("is_primary"))
        personas = [Persona(**r) for r in rows] or [state["primary_persona"]]
        result = run_focus_group(
            state["creative"], personas, user_id=state.get("user_id"), target_language=state.get("target_language", "en")
        )
        upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], focus_group=result.model_dump())
    except Exception as exc:  # never block the gate on advice
        log.warning("focus group skipped: %s", exc)
    return {}
