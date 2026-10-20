import os

from groq import Groq

from src.providers.base import LLMProvider

# Groq retired llama-3.3-70b-versatile (404 model_not_found, 2026-10); this is
# the largest model left on its free tier.
MODEL = "openai/gpt-oss-120b"


class GroqLLMProvider(LLMProvider):
    def __init__(self) -> None:
        # The free tier caps gpt-oss-120b at 8,000 tokens/minute per account, so
        # 429s are routine (eval CI, workers and scripts share the budget). The
        # SDK honours Groq's retry-after and backs off between attempts; 8
        # retries rides out a busy minute instead of crashing the run.
        self._client = Groq(api_key=os.environ["GROQ_API_KEY"], max_retries=8)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        completion = self._client.chat.completions.create(model=MODEL, messages=messages)
        return completion.choices[0].message.content or ""
