"""Gemini image generation (Interactions API), second in the free tier's image
chain when GEMINI_API_KEY is set. Google has no free tier for image models,
so the key's project needs billing; without it calls fail and the registry's
fallback chain moves on to Pollinations (see FallbackImageProvider)."""
import base64
import logging
import os

import requests

from src.providers.base import ImageProvider

logger = logging.getLogger("providers.gemini_image")

INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
# The cheapest 1K-only image model; override with GEMINI_IMAGE_MODEL.
DEFAULT_MODEL = "gemini-3.1-flash-lite-image"
TIMEOUT_SECONDS = 90
# Errors that won't fix themselves within a run (bad key, no billing, quota):
# stop calling Gemini for the rest of this process instead of paying the
# round trip on every image.
_PERMANENT_STATUSES = {400, 401, 403, 404, 429}


def _find_image(node) -> str | None:
    """Base64 data of the last image block anywhere in the response."""
    found = None
    if isinstance(node, dict):
        if node.get("type") == "image" and isinstance(node.get("data"), str):
            found = node["data"]
        for key, value in node.items():
            if key == "output_image" and isinstance(value, dict) and isinstance(value.get("data"), str):
                found = value["data"]
            else:
                found = _find_image(value) or found
    elif isinstance(node, list):
        for item in node:
            found = _find_image(item) or found
    return found


class GeminiImageProvider(ImageProvider):
    disabled_reason: str | None = None  # set process-wide after a permanent error

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self._api_key = api_key or os.environ["GEMINI_API_KEY"]
        self._model = model or os.environ.get("GEMINI_IMAGE_MODEL") or DEFAULT_MODEL

    def generate_image(self, prompt: str) -> bytes:
        if GeminiImageProvider.disabled_reason:
            raise RuntimeError(f"Gemini image generation unavailable: {GeminiImageProvider.disabled_reason}")
        response = requests.post(
            INTERACTIONS_URL,
            headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
            json={
                "model": self._model,
                "input": [{"type": "text", "text": prompt}],
                "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "1:1", "image_size": "1K"},
            },
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code in _PERMANENT_STATUSES:
            # The status only: error bodies can echo request details.
            GeminiImageProvider.disabled_reason = f"HTTP {response.status_code}"
        response.raise_for_status()
        data = _find_image(response.json())
        if not data:
            raise RuntimeError("Gemini returned no image")
        return base64.b64decode(data)


class FallbackImageProvider(ImageProvider):
    """Tries each provider in order; one flaky or unpaid API never fails a run."""

    def __init__(self, providers: list[ImageProvider]) -> None:
        self._providers = providers

    def generate_image(self, prompt: str) -> bytes:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                return provider.generate_image(prompt)
            except Exception as exc:
                last_error = exc
                logger.warning("%s failed, trying the next image provider: %s", type(provider).__name__, exc)
        raise last_error or RuntimeError("no image providers configured")
