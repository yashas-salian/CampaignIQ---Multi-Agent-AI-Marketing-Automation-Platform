import os

from openai import OpenAI

from src.providers.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible chat endpoint: the free-tier fallbacks behind Groq
    (Cerebras, OpenRouter, Gemini) all speak this protocol."""

    free_tier = True

    def __init__(self, name: str, *, base_url: str, api_key: str, model: str, max_retries: int = 1) -> None:
        self.name = name
        self.model = model
        self._client = OpenAI(base_url=base_url, api_key=api_key, max_retries=max_retries, timeout=60)

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        completion = self._client.chat.completions.create(model=self.model, messages=messages)
        self.last_usage = getattr(completion, "usage", None)
        return completion.choices[0].message.content or ""


# Free-tier fallbacks, tried in this order after Groq. Same model first
# (gpt-oss-120b on Cerebras/OpenRouter) so output quality doesn't shift when
# Groq's daily budget runs out; Gemini Flash is the last resort. A provider
# joins the chain only when its API key is set; *_MODEL overrides the model.
FALLBACKS = [
    ("cerebras", "CEREBRAS_API_KEY", "https://api.cerebras.ai/v1", "gpt-oss-120b"),
    ("openrouter", "OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "openai/gpt-oss-120b:free"),
    ("gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.5-flash"),
]


def configured_fallbacks() -> list[OpenAICompatibleProvider]:
    providers = []
    for name, key_env, base_url, model in FALLBACKS:
        api_key = os.environ.get(key_env)
        if api_key:
            model = os.environ.get(f"{name.upper()}_MODEL") or model
            providers.append(OpenAICompatibleProvider(name, base_url=base_url, api_key=api_key, model=model))
    return providers
