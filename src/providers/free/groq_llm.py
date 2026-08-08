import os

from groq import Groq

from src.providers.base import LLMProvider

MODEL = "llama-3.3-70b-versatile"


class GroqLLMProvider(LLMProvider):
    def __init__(self) -> None:
        self._client = Groq(api_key=os.environ["GROQ_API_KEY"])

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        completion = self._client.chat.completions.create(model=MODEL, messages=messages)
        return completion.choices[0].message.content or ""
