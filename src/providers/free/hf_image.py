"""FLUX.1-schnell through Hugging Face Inference Providers, the free tier's
first-choice image model (HF_TOKEN with the "Make calls to Inference
Providers" permission). It runs on HF's monthly free credit; once that's
spent calls fail with 402 and the registry's fallback chain moves on
(see FallbackImageProvider)."""
import io
import os

from src.providers.base import ImageProvider

# Override with HF_IMAGE_MODEL / HF_IMAGE_PROVIDER ("auto" = the first live
# partner in the account's provider order; hf-inference itself no longer serves FLUX).
DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"
DEFAULT_PROVIDER = "auto"
TIMEOUT_SECONDS = 120
# Out of credit, bad token or permission, model gone: don't retry for the rest of the process.
_PERMANENT_STATUSES = {401, 402, 403, 404, 410}


class HuggingFaceImageProvider(ImageProvider):
    disabled_reason: str | None = None  # set process-wide after a permanent error

    def __init__(self, token: str | None = None, model: str | None = None) -> None:
        self._token = token or os.environ["HF_TOKEN"]
        self._model = model or os.environ.get("HF_IMAGE_MODEL") or DEFAULT_MODEL
        self._provider = os.environ.get("HF_IMAGE_PROVIDER") or DEFAULT_PROVIDER

    def generate_image(self, prompt: str) -> bytes:
        if HuggingFaceImageProvider.disabled_reason:
            raise RuntimeError(f"Hugging Face image generation unavailable: {HuggingFaceImageProvider.disabled_reason}")
        from huggingface_hub import InferenceClient  # comes with sentence-transformers

        client = InferenceClient(provider=self._provider, api_key=self._token, timeout=TIMEOUT_SECONDS)
        try:
            image = client.text_to_image(prompt, model=self._model, width=1024, height=1024)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in _PERMANENT_STATUSES:
                # The status only: error bodies can echo account details.
                HuggingFaceImageProvider.disabled_reason = f"HTTP {status}"
            raise
        out = io.BytesIO()
        image.convert("RGB").save(out, format="JPEG", quality=92)
        return out.getvalue()
