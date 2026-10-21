import logging
import os

from src.providers.base import ImageProvider, LLMProvider
from src.providers.free.groq_llm import GroqLLMProvider
from src.providers.free.openai_compatible import configured_fallbacks
from src.providers.gateway import LLMGateway
from src.providers.free.pollinations_image import PollinationsImageProvider
from src.providers.paid.openai_image import OpenAIImageProvider
from src.providers.paid.openai_llm import OpenAILLMProvider

logger = logging.getLogger("providers.registry")


def _free_llm(user_id: str | None) -> LLMProvider:
    """Groq, plus any configured free fallbacks behind it (see gateway.py).
    The `llm_fallback` flag is the kill switch for the fallbacks."""
    from src.flags import is_enabled

    fallbacks = configured_fallbacks() if is_enabled("llm_fallback", user_id, default=True) else []
    groq = GroqLLMProvider(max_retries=2 if fallbacks else 8)
    return LLMGateway([groq, *fallbacks], user_id=user_id)


def _force_free_tier() -> bool:
    return os.environ.get("FORCE_FREE_TIER", "false").lower() == "true"


def _byok_key(user_id: str, capability: str) -> str | None:
    # Lazy import: src.db.supabase_client imports capabilities.audience for
    # the Persona type, and capabilities import this module for get_llm() —
    # a module-level import here would create a circular import.
    from src.db.supabase_client import get_client

    # Keys live in Supabase Vault; read_provider_key() is service-role only.
    vaulted = get_client().rpc("read_provider_key", {"p_user_id": user_id, "p_capability": capability}).execute()
    if vaulted.data:
        return vaulted.data

    # Legacy rows (AES-encrypted before the Vault move, until
    # src/admin/migrate_keys_to_vault.py has run).
    result = (
        get_client()
        .table("provider_keys")
        .select("encrypted_key")
        .eq("user_id", user_id)
        .eq("capability", capability)
        .maybe_single()
        .execute()
    )
    if not result or not result.data or not result.data.get("encrypted_key"):
        return None
    from src.providers.crypto import decrypt_key

    return decrypt_key(result.data["encrypted_key"])


def _is_subscribed(user_id: str) -> bool:
    from src.db.supabase_client import get_client

    result = (
        get_client().table("subscriptions").select("status").eq("user_id", user_id).maybe_single().execute()
    )
    return bool(result and result.data and result.data["status"] == "subscribed")


def has_paid_tier_access(user_id: str | None) -> bool:
    """Subscribed, or has at least one BYOK key set for any capability."""
    if not user_id:
        return False
    if _is_subscribed(user_id):
        return True
    from src.db.supabase_client import get_client

    result = get_client().table("provider_keys").select("id").eq("user_id", user_id).limit(1).execute()
    return bool(result.data)


def get_llm(user_id: str | None = None) -> LLMProvider:
    if user_id and not _force_free_tier():
        byok = _byok_key(user_id, "llm")
        if byok:
            logger.info("provider tier resolved: llm=byok (user=%s)", user_id)
            return OpenAILLMProvider(api_key=byok)
        if _is_subscribed(user_id) and os.environ.get("PAID_LLM_API_KEY"):
            logger.info("provider tier resolved: llm=paid-subscribed (user=%s)", user_id)
            return OpenAILLMProvider()
    elif not _force_free_tier() and os.environ.get("PAID_LLM_API_KEY"):
        logger.info("provider tier resolved: llm=paid (no user context)")
        return OpenAILLMProvider()
    logger.info("provider tier resolved: llm=free (Groq + fallbacks)")
    return _free_llm(user_id)


def get_image_generator(user_id: str | None = None) -> ImageProvider:
    if user_id and not _force_free_tier():
        byok = _byok_key(user_id, "image")
        if byok:
            logger.info("provider tier resolved: image=byok (user=%s)", user_id)
            return OpenAIImageProvider(api_key=byok)
        if _is_subscribed(user_id) and (os.environ.get("PAID_IMAGE_API_KEY") or os.environ.get("PAID_LLM_API_KEY")):
            logger.info("provider tier resolved: image=paid-subscribed (user=%s)", user_id)
            return OpenAIImageProvider()
    elif not _force_free_tier() and (os.environ.get("PAID_IMAGE_API_KEY") or os.environ.get("PAID_LLM_API_KEY")):
        logger.info("provider tier resolved: image=paid (no user context)")
        return OpenAIImageProvider()
    logger.info("provider tier resolved: image=free (Pollinations)")
    return PollinationsImageProvider()


def get_judge_llm(user_id: str | None = None) -> LLMProvider:
    if user_id and not _force_free_tier():
        byok = _byok_key(user_id, "judge")
        if byok:
            logger.info("provider tier resolved: judge=byok (user=%s)", user_id)
            return OpenAILLMProvider(api_key=byok)
        if _is_subscribed(user_id) and os.environ.get("PAID_JUDGE_API_KEY"):
            logger.info("provider tier resolved: judge=paid-subscribed (user=%s)", user_id)
            return OpenAILLMProvider(api_key=os.environ["PAID_JUDGE_API_KEY"])
    elif not _force_free_tier() and os.environ.get("PAID_JUDGE_API_KEY"):
        logger.info("provider tier resolved: judge=paid (no user context)")
        return OpenAILLMProvider(api_key=os.environ["PAID_JUDGE_API_KEY"])
    logger.info("provider tier resolved: judge=free (Groq + fallbacks, same as agents)")
    return _free_llm(user_id)
