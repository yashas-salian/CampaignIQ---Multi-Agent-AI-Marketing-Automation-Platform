import os

from groq import Groq

from src.providers.base import LLMProvider

# Groq retired llama-3.3-70b-versatile (404 model_not_found, 2026-10); this is
# the largest model left on its free tier.
MODEL = "openai/gpt-oss-120b"


class GroqLLMProvider(LLMProvider):
    name = "groq"
    model = MODEL
    free_tier = True

    def __init__(self, max_retries: int = 8) -> None:
        # The free tier caps gpt-oss-120b at 8,000 tokens/minute per account, so
        # 429s are routine (eval CI, workers and scripts share the budget). The
        # SDK honours Groq's retry-after and backs off between attempts; 8
        # retries rides out a busy minute instead of crashing the run. With
        # fallback providers configured the gateway passes fewer, so a spent
        # budget fails over in seconds instead of waiting minutes.
        self._client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=max_retries)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        completion = self._client.chat.completions.create(model=MODEL, messages=messages)
        self.last_usage = getattr(completion, "usage", None)
        return completion.choices[0].message.content or ""
