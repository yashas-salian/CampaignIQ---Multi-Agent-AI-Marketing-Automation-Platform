"""LLM gateway: provider fallback + usage accounting for the free tier.

The free tier runs on shared free APIs whose limits are the most common reason
a run failed (Groq: 8k tokens/minute, 200k tokens/day). The gateway tries each
configured provider in order; a rate limit, outage or bad key on one moves the
call to the next one and benches the failing provider for a while (an hour
when its daily budget is gone), so later calls in the same run skip straight
past it. Every call's token usage is recorded in `llm_usage` (best effort),
the basis for per-tenant limits and cost dashboards.

BYOK and paid-tier users never go through here: their prompts stay with the
provider they chose.
"""
import logging
import re
import time

from src.observability import generation
from src.prompts import current_prompt
from src.providers.base import LLMProvider
from src.usage import current_org

logger = logging.getLogger("providers.gateway")

# provider name -> monotonic time it may be tried again. Module-level so the
# bench is shared by every gateway in the process (one run = one process).
_benched_until: dict[str, float] = {}
# After a failed usage write (no DB credentials locally, DB down), stop trying
# for a while instead of paying for a failing insert on every call.
_recording_paused_until = 0.0


def _cooldown_seconds(exc: Exception) -> float:
    status = getattr(exc, "status_code", None)
    message = str(exc).lower()
    if status == 429:
        # Daily budgets don't come back in a minute; per-minute ones do.
        return 3600 if re.search(r"per day|tpd|rpd|daily", message) else 60
    if status in (401, 403):
        return 3600  # bad or revoked key: don't keep hammering it
    if status is None or status >= 500 or status == 408:
        return 30  # timeout, connection error, provider outage
    return 0  # e.g. 400 for this provider's request: try others, don't bench


class AllProvidersFailed(RuntimeError):
    pass


class LLMGateway(LLMProvider):
    free_tier = True

    def __init__(self, providers: list[LLMProvider], *, user_id: str | None = None) -> None:
        if not providers:
            raise ValueError("LLMGateway needs at least one provider")
        self.providers = providers
        self.user_id = user_id

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        errors: list[tuple[str, Exception]] = []
        now = time.monotonic()
        candidates = [p for p in self.providers if _benched_until.get(_name(p), 0) <= now]
        # Everything benched: still try them all rather than fail without a call.
        for provider in candidates or self.providers:
            name = _name(provider)
            started = time.monotonic()
            with generation(name, getattr(provider, "model", None), prompt=prompt, system=system,
                            user_id=self.user_id, org_id=current_org.get(), prompt_ref=current_prompt.get(),
                            fallback=bool(errors)) as trace:
                try:
                    text = provider.generate(prompt, system=system)
                except Exception as exc:
                    trace.failed(_short(exc))
                    failure = exc
                else:
                    trace.done(text, getattr(provider, "last_usage", None))
                    failure = None
            if failure is not None:
                exc = failure
                cooldown = _cooldown_seconds(exc)
                if cooldown:
                    _benched_until[name] = time.monotonic() + cooldown
                logger.warning("LLM provider %s failed (%s); trying the next one", name, _short(exc))
                _record(self.user_id, provider, started, ok=False, error=_short(exc))
                errors.append((name, exc))
                continue
            _record(self.user_id, provider, started, ok=True)
            if errors:
                logger.info("LLM call served by fallback provider %s", name)
            return text
        first = errors[0][1]
        raise AllProvidersFailed(
            "every LLM provider failed: " + "; ".join(f"{n}: {_short(e)}" for n, e in errors)
        ) from first


def _name(provider: LLMProvider) -> str:
    return getattr(provider, "name", type(provider).__name__)


def _short(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


def _record(user_id: str | None, provider: LLMProvider, started: float, *, ok: bool, error: str | None = None) -> None:
    """Best effort: accounting must never fail or slow down a run noticeably."""
    global _recording_paused_until
    if time.monotonic() < _recording_paused_until:
        return
    usage = getattr(provider, "last_usage", None) if ok else None
    row = {
        "user_id": user_id,
        "org_id": current_org.get(),
        "prompt": current_prompt.get(),
        "provider": _name(provider),
        "model": getattr(provider, "model", None),
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "latency_ms": int((time.monotonic() - started) * 1000),
        "ok": ok,
        "error": error,
    }
    try:
        from src.db.supabase_client import get_client

        get_client().table("llm_usage").insert(row).execute()
    except Exception as exc:
        _recording_paused_until = time.monotonic() + 300
        logger.debug("llm_usage not recorded (pausing for 5 min): %s", exc)


def reset_bench() -> None:
    global _recording_paused_until
    _benched_until.clear()
    _recording_paused_until = 0.0
