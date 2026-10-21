from abc import ABC, abstractmethod


class LLMProvider(ABC):
    # True for the shared free-tier providers (and the gateway over them):
    # free-tier-only behaviour, like the M7 local classifier, keys off this.
    free_tier: bool = False

    @abstractmethod
    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Return a text completion for the given prompt."""


class ImageProvider(ABC):
    supports_outpainting: bool = False

    @abstractmethod
    def generate_image(self, prompt: str) -> bytes:
        """Return raw image bytes for the given prompt."""

    def outpaint(self, template_bytes: bytes, prompt: str) -> bytes:
        """Use template_bytes as a fixed foundation and generate new content
        around it, preserving its pixels exactly. Only providers with
        supports_outpainting = True override this."""
        raise NotImplementedError(f"{type(self).__name__} does not support outpainting")
