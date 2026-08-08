import logging
import os

from src.providers.base import ImageProvider, LLMProvider
from src.providers.free.groq_llm import GroqLLMProvider
from src.providers.free.pollinations_image import PollinationsImageProvider
from src.providers.paid.openai_image import OpenAIImageProvider
from src.providers.paid.openai_llm import OpenAILLMProvider

logger = logging.getLogger("providers.registry")


def _force_free_tier() -> bool:
    return os.environ.get("FORCE_FREE_TIER", "false").lower() == "true"


def get_llm() -> LLMProvider:
    if not _force_free_tier() and os.environ.get("PAID_LLM_API_KEY"):
        logger.info("provider tier resolved: llm=paid (OpenAI)")
        return OpenAILLMProvider()
    logger.info("provider tier resolved: llm=free (Groq)")
    return GroqLLMProvider()


def get_image_generator() -> ImageProvider:
    if not _force_free_tier() and (os.environ.get("PAID_IMAGE_API_KEY") or os.environ.get("PAID_LLM_API_KEY")):
        logger.info("provider tier resolved: image=paid (OpenAI)")
        return OpenAIImageProvider()
    logger.info("provider tier resolved: image=free (Pollinations)")
    return PollinationsImageProvider()


def get_judge_llm() -> LLMProvider:
    if not _force_free_tier() and os.environ.get("PAID_JUDGE_API_KEY"):
        logger.info("provider tier resolved: judge=paid (OpenAI)")
        return OpenAILLMProvider(api_key=os.environ["PAID_JUDGE_API_KEY"])
    logger.info("provider tier resolved: judge=free (Groq, same as agents)")
    return GroqLLMProvider()
