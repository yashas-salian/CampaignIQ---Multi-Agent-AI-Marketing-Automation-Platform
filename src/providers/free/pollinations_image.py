from src.providers.base import ImageProvider
from src.tools.image_gen import generate_pollinations_image


class PollinationsImageProvider(ImageProvider):
    def generate_image(self, prompt: str) -> bytes:
        return generate_pollinations_image(prompt)
