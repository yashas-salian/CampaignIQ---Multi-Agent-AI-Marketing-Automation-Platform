import os

from openai import OpenAI

from src.providers.base import LLMProvider

MODEL = "gpt-4o"


class OpenAILLMProvider(LLMProvider):
    def __init__(self, api_key: str | None = None) -> None:
        self._client = OpenAI(api_key=api_key or os.environ["PAID_LLM_API_KEY"])

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        completion = self._client.chat.completions.create(model=MODEL, messages=messages)
        return completion.choices[0].message.content or ""
