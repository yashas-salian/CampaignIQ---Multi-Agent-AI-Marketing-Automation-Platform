from urllib.parse import quote

import requests

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"


def generate_pollinations_image(prompt: str, *, width: int = 1024, height: int = 1024, seed: int | None = None) -> bytes:
    url = POLLINATIONS_URL.format(prompt=quote(prompt))
    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()
    return response.content
