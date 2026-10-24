"""FLUX.1-schnell on Cloudflare Workers AI, first in the free tier's image chain
(CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN with Workers AI permission).
It runs on Cloudflare's free daily allowance; once that's spent calls fail
and the registry's fallback chain moves on (see FallbackImageProvider)."""
import base64
import os

import requests

from src.providers.base import ImageProvider

RUN_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
# Override with CLOUDFLARE_IMAGE_MODEL.
DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
STEPS = 8  # the model's maximum: noticeably sharper than the default 4, still a few seconds
TIMEOUT_SECONDS = 90
# Bad token or account, no permission, model gone: don't retry for the rest of the process.
# (429, the daily allowance running out, is left retryable per call: it resets.)
_PERMANENT_STATUSES = {400, 401, 403, 404}


def configured() -> bool:
    return bool(os.environ.get("CLOUDFLARE_ACCOUNT_ID") and os.environ.get("CLOUDFLARE_API_TOKEN"))


class CloudflareImageProvider(ImageProvider):
    disabled_reason: str | None = None  # set process-wide after a permanent error

    def __init__(self) -> None:
        self._account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self._token = os.environ["CLOUDFLARE_API_TOKEN"]
        self._model = os.environ.get("CLOUDFLARE_IMAGE_MODEL") or DEFAULT_MODEL

    def generate_image(self, prompt: str) -> bytes:
        if CloudflareImageProvider.disabled_reason:
            raise RuntimeError(f"Cloudflare image generation unavailable: {CloudflareImageProvider.disabled_reason}")
        response = requests.post(
            RUN_URL.format(account=self._account, model=self._model),
            headers={"Authorization": f"Bearer {self._token}"},
            json={"prompt": prompt[:2048], "steps": STEPS},
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code in _PERMANENT_STATUSES:
            # The status only: error bodies can echo account details.
            CloudflareImageProvider.disabled_reason = f"HTTP {response.status_code}"
        response.raise_for_status()
        body = response.json()
        image = (body.get("result") or {}).get("image") or body.get("image")
        if not image:
            raise RuntimeError("Cloudflare returned no image")
        return base64.b64decode(image)
