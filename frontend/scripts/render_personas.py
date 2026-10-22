"""Render the persona character set (frontend/public/personas/<archetype>.webp).

One-off asset generation with Pollinations (free), the same image service the
app uses. Every figure shares one style prompt and background so the set reads
as one family; each archetype has a fixed seed, so re-running reproduces it.
The archetype list must match ARCHETYPES in src/capabilities/audience.py.

    python frontend/scripts/render_personas.py            # all missing figures
    python frontend/scripts/render_personas.py chef nurse # re-render some
"""
import io
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "public" / "personas"
SIZE = 384

STYLE = (
    "stylized 3D character render in the style of a modern animated film, friendly expression, "
    "head and upper body, centered, facing the viewer, soft studio lighting, smooth clay-like materials, "
    "subtle warm orange accents, plain soft peach background, no text, no logo, high quality"
)

# archetype -> (who, what they hold or wear). A mix of genders, ages and ethnicities across the set.
CHARACTERS = {
    "teacher": ("a South Asian woman teacher in her thirties", "holding a stack of books, wearing a cardigan"),
    "doctor": ("a Black male doctor in his forties", "wearing a white coat with a stethoscope around his neck"),
    "nurse": ("an East Asian woman nurse", "wearing teal scrubs, holding a clipboard"),
    "student": ("a young Latino college student", "wearing a hoodie and a backpack, holding a notebook"),
    "developer": ("a young woman software developer with glasses", "holding an open laptop, wearing headphones around her neck"),
    "chef": ("a middle-aged white male chef", "wearing a chef's hat and apron, holding a frying pan"),
    "athlete": ("a young Black woman athlete", "in sportswear with a water bottle and a towel over her shoulder"),
    "parent": ("a smiling father in his thirties", "carrying a toddler on his hip, wearing a casual shirt"),
    "retiree": ("a cheerful grey-haired South Asian grandmother", "wearing a shawl and glasses, holding a cup of tea"),
    "professional": ("a Middle Eastern man office professional", "in a blazer, holding a coffee cup and a tablet"),
    "entrepreneur": ("a young African woman small-business owner", "wearing an apron over smart clothes, holding a shop sign that is blank"),
    "designer": ("a creative designer with colourful hair", "holding a stylus and a drawing tablet"),
    "farmer": ("an older Indian farmer", "wearing a straw hat, holding a basket of fresh vegetables"),
    "traveler": ("a young woman traveller", "with a large backpack and a folded map, wearing a sun hat"),
    "gamer": ("a teenage boy gamer", "wearing a gaming headset, holding a game controller"),
    "scientist": ("an East Asian man scientist", "wearing a lab coat and safety goggles, holding a test tube"),
    "tradesperson": ("a woman construction worker", "wearing a hard hat and hi-vis vest, holding a wrench"),
    "finance": ("a Black man finance analyst", "wearing a shirt and tie, holding a tablet showing a rising chart"),
    "creator": ("a young social media creator", "holding a smartphone on a small tripod with a ring light"),
    "general": ("a friendly young person", "in casual clothes, waving hello"),
}


def crop_watermark(img: Image.Image) -> Image.Image:
    # Pollinations stamps a small credit bottom-right even with nologo: keep the
    # top-centred 88% square (the face and props sit there anyway).
    w, h = img.size
    side = int(min(w, h) * 0.88)
    left = (w - side) // 2
    return img.crop((left, 0, left + side, side))


def render(archetype: str, seed: int) -> None:
    who, props = CHARACTERS[archetype]
    prompt = f"{who}, {props}, {STYLE}"
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
    for attempt in range(4):
        try:
            r = requests.get(url, params={"width": 768, "height": 768, "seed": seed, "nologo": "true", "model": "flux"}, timeout=180)
            r.raise_for_status()
            img = crop_watermark(Image.open(io.BytesIO(r.content)).convert("RGB")).resize((SIZE, SIZE), Image.LANCZOS)
            OUT.mkdir(parents=True, exist_ok=True)
            img.save(OUT / f"{archetype}.webp", "WEBP", quality=82, method=6)
            print(f"ok {archetype} ({(OUT / f'{archetype}.webp').stat().st_size // 1024} KB)", flush=True)
            return
        except Exception as exc:  # Pollinations is free and occasionally slow: back off and retry
            print(f"retry {archetype}: {exc}", flush=True)
            time.sleep(5 * (attempt + 1))
    print(f"FAILED {archetype}", flush=True)


if __name__ == "__main__":
    wanted = sys.argv[1:] or [a for a in CHARACTERS if not (OUT / f"{a}.webp").exists()]
    for index, name in enumerate(CHARACTERS):
        if name in wanted:
            render(name, seed=4200 + index)
