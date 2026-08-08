import base64
import os

from openai import OpenAI

from src.providers.base import ImageProvider

MODEL = "dall-e-3"


class OpenAIImageProvider(ImageProvider):
    def __init__(self) -> None:
        self._client = OpenAI(api_key=os.environ.get("PAID_IMAGE_API_KEY") or os.environ["PAID_LLM_API_KEY"])

    def generate_image(self, prompt: str) -> bytes:
        result = self._client.images.generate(model=MODEL, prompt=prompt, size="1024x1024", response_format="b64_json")
        return base64.b64decode(result.data[0].b64_json)
