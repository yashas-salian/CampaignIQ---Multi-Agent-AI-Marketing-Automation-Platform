"""Organisation context for a worker run, and the daily AI budget check.

The worker sets the organisation once per run (`use_org`); the LLM gateway
attributes every call's tokens to it in `llm_usage`, which is what the plan's
daily token budget is measured against (see *_usage_limits.sql).
"""
import logging
from contextvars import ContextVar

logger = logging.getLogger("usage")

current_org: ContextVar[str | None] = ContextVar("current_org", default=None)


def use_org(org_id: str | None) -> None:
    current_org.set(org_id)


def personal_org(user_id: str) -> str | None:
    """The user's personal organisation (created on demand)."""
    try:
        from src.db.supabase_client import get_client

        return get_client().rpc("ensure_personal_org", {"p_user": user_id}).execute().data
    except Exception as exc:
        logger.warning("could not resolve personal org for %s: %s", user_id, exc)
        return None


def budget_exhausted(org_id: str | None) -> str | None:
    """The reason this organisation can't spend more AI tokens today, or None.
    Fails open: a failed check never blocks a run."""
    if not org_id:
        return None
    try:
        from src.db.supabase_client import get_client

        return get_client().rpc("token_budget_error", {"p_org": org_id}).execute().data
    except Exception as exc:
        logger.warning("token budget check failed for %s: %s", org_id, exc)
        return None
