import base64
import io
import os

from openai import OpenAI
from PIL import Image

from src.providers.base import ImageProvider

# dall-e-3 was retired from the OpenAI API on 2026-05-12; gpt-image-2 is its
# replacement and is also the model that supports images.edit()-based
# outpainting used below.
MODEL = "gpt-image-2"
CANVAS_SIZE = (1024, 1024)


class OpenAIImageProvider(ImageProvider):
    supports_outpainting = True

    def __init__(self, api_key: str | None = None) -> None:
        self._client = OpenAI(api_key=api_key or os.environ.get("PAID_IMAGE_API_KEY") or os.environ["PAID_LLM_API_KEY"])

    def generate_image(self, prompt: str) -> bytes:
        result = self._client.images.generate(model=MODEL, prompt=prompt, size="1024x1024", response_format="b64_json")
        return base64.b64decode(result.data[0].b64_json)

    def outpaint(self, template_bytes: bytes, prompt: str) -> bytes:
        template = Image.open(io.BytesIO(template_bytes)).convert("RGBA")
        offset = ((CANVAS_SIZE[0] - template.width) // 2, (CANVAS_SIZE[1] - template.height) // 2)

        canvas = Image.new("RGBA", CANVAS_SIZE, (255, 255, 255, 255))
        canvas.paste(template, offset)

        # Mask: opaque over the template's exact footprint (preserve those
        # pixels untouched), fully transparent everywhere else -- images.edit
        # regenerates only the mask's transparent region.
        mask = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        preserved = Image.new("RGBA", template.size, (0, 0, 0, 255))
        mask.paste(preserved, offset)

        image_buf = io.BytesIO()
        canvas.save(image_buf, format="PNG")
        image_buf.seek(0)
        mask_buf = io.BytesIO()
        mask.save(mask_buf, format="PNG")
        mask_buf.seek(0)

        result = self._client.images.edit(
            model=MODEL,
            image=image_buf,
            mask=mask_buf,
            prompt=prompt,
            size="1024x1024",
            response_format="b64_json",
        )
        return base64.b64decode(result.data[0].b64_json)
