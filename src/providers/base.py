from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a text completion for the given prompt."""


class ImageProvider(ABC):
    @abstractmethod
    def generate_image(self, prompt: str) -> bytes:
        """Return raw image bytes for the given prompt."""
