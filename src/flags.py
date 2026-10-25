"""Feature flags for the Python side (graph, workers, MCP server).

Evaluated by the database function feature_enabled_for() (see
supabase/migrations/*_feature_flags.sql), the same rule the frontend uses, so a
percentage rollout puts the same users in on both sides.

    from src.flags import is_enabled
    if is_enabled("llm_fallback", user_id): ...

Precedence: env override FLAG_<KEY>=true|false (tests, local dev, emergency
kill switch without a DB write) -> database -> the caller's default. A flag
lookup can never break a run: any failure returns the default.
"""
import logging
import os
import time

logger = logging.getLogger("flags")

CACHE_SECONDS = 60
_cache: dict[tuple[str, str | None], tuple[float, bool]] = {}


def _env_override(key: str) -> bool | None:
    value = os.environ.get(f"FLAG_{key.upper()}")
    if value is None or value.strip() == "":
        return None
    return value.strip().lower() in ("1", "true", "on", "yes")


def is_enabled(key: str, user_id: str | None = None, *, default: bool = False) -> bool:
    override = _env_override(key)
    if override is not None:
        return override

    cache_key = (key, user_id)
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    try:
        from src.db.supabase_client import get_client

        result = get_client().rpc("feature_enabled_for", {"flag_key": key, "uid": user_id}).execute()
        value = bool(result.data)
        # The database answers "false" for a flag that has no row at all; for a
        # flag that defaults to on (llm_fallback) that must mean "not set",
        # not "switched off".
        if not value and default:
            row = get_client().table("feature_flags").select("key").eq("key", key).limit(1).execute()
            if not row.data:
                value = default
    except Exception as exc:  # DB down, migration not applied, no credentials
        logger.warning("feature flag %s lookup failed (%s) -> default %s", key, exc, default)
        return default

    _cache[cache_key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    _cache.clear()
