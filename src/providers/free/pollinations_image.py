import io
import random

from PIL import Image

from src.providers.base import ImageProvider
from src.tools.image_gen import generate_pollinations_image

# Pollinations stamps its name in the bottom-right corner (even with nologo on
# the anonymous tier): ask for a taller picture and cut that strip off.
WATERMARK_STRIP = 64
SIZE = 1024


class PollinationsImageProvider(ImageProvider):
    def generate_image(self, prompt: str) -> bytes:
        # A fresh seed each call: without one Pollinations returns the same
        # picture for the same prompt, so "New picture" would change nothing.
        raw = generate_pollinations_image(
            prompt, width=SIZE, height=SIZE + WATERMARK_STRIP, seed=random.randint(1, 2_000_000_000)
        )
        try:
            image = Image.open(io.BytesIO(raw)).convert("RGB")
        except Exception:
            return raw  # not an image we can read: pass it on untouched
        strip = round(WATERMARK_STRIP * image.height / (SIZE + WATERMARK_STRIP))
        out = io.BytesIO()
        image.crop((0, 0, image.width, image.height - strip)).save(out, format="JPEG", quality=92)
        return out.getvalue()
