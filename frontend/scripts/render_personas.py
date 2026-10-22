"""Render the persona character set (frontend/public/personas/<archetype>-<gender>.webp).

One-off asset generation with Pollinations (free), the same image service the
app uses. Every figure shares one style prompt and background so the set reads
as one family; each figure has a fixed seed, so re-running reproduces it.
Each archetype has a female and a male figure, so a persona's figure always
matches the gender the AI gave it. The archetype list must match ARCHETYPES in
src/capabilities/audience.py.

    python frontend/scripts/render_personas.py                       # all missing figures
    python frontend/scripts/render_personas.py chef-female nurse-male # re-render some
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

GENDERS = ("female", "male")

# archetype -> (female who, male who, what they hold or wear). Ages and ethnicities vary across the set.
CHARACTERS = {
    "teacher": ("a South Asian woman teacher in her thirties", "a white man teacher in his forties with a beard", "holding a stack of books, wearing a cardigan"),
    "doctor": ("a Latina woman doctor in her forties", "a Black male doctor in his forties", "wearing a white coat with a stethoscope around the neck"),
    "nurse": ("an East Asian woman nurse", "a young Black man nurse", "wearing teal scrubs, holding a clipboard"),
    "student": ("a young South Asian woman college student", "a young Latino man college student", "wearing a hoodie and a backpack, holding a notebook"),
    "developer": ("a young woman software developer with glasses", "a young South Asian man software developer", "holding an open laptop, wearing headphones around the neck"),
    "chef": ("a Black woman chef in her thirties", "a middle-aged white male chef", "wearing a chef's hat and apron, holding a frying pan"),
    "athlete": ("a young Black woman athlete", "a young East Asian man athlete", "in sportswear with a water bottle and a towel over one shoulder"),
    "parent": ("a smiling mother in her thirties", "a smiling father in his thirties", "carrying a toddler on the hip, wearing a casual shirt"),
    "retiree": ("a cheerful grey-haired South Asian grandmother", "a cheerful grey-haired white grandfather", "wearing a cardigan and glasses, holding a cup of tea"),
    "professional": ("an East Asian woman office professional", "a Middle Eastern man office professional", "in a blazer, holding a coffee cup and a tablet"),
    "entrepreneur": ("a young African woman small-business owner", "a young Indian man small-business owner", "wearing an apron over smart clothes, holding a blank shop sign"),
    "designer": ("a woman creative designer with colourful hair", "a man creative designer with a beanie", "holding a stylus and a drawing tablet"),
    "farmer": ("an Indian woman farmer", "an older Indian man farmer", "wearing a straw hat, holding a basket of fresh vegetables"),
    "traveler": ("a young woman traveller", "a young man traveller with a beard", "with a large backpack and a folded map, wearing a sun hat"),
    "gamer": ("a teenage girl gamer", "a teenage boy gamer", "wearing a gaming headset, holding a game controller"),
    "scientist": ("a Black woman scientist", "an East Asian man scientist", "wearing a lab coat and safety goggles, holding a test tube"),
    "tradesperson": ("a woman construction worker", "a Latino man construction worker", "wearing a hard hat and hi-vis vest, holding a wrench"),
    "finance": ("a South Asian woman finance analyst", "a Black man finance analyst", "in smart office clothes, holding a tablet showing a rising chart"),
    "creator": ("a young woman social media creator", "a young man social media creator", "holding a smartphone on a small tripod with a ring light"),
    "general": ("a friendly young woman", "a friendly young man", "in casual clothes, waving hello"),
}
FIGURES = [f"{a}-{g}" for a in CHARACTERS for g in GENDERS]


def crop_watermark(img: Image.Image) -> Image.Image:
    # Pollinations stamps a small credit bottom-right even with nologo: keep the
    # top-centred 88% square (the face and props sit there anyway).
    w, h = img.size
    side = int(min(w, h) * 0.88)
    left = (w - side) // 2
    return img.crop((left, 0, left + side, side))


def render(figure: str, seed: int) -> None:
    archetype, gender = figure.rsplit("-", 1)
    female, male, props = CHARACTERS[archetype]
    prompt = f"{female if gender == 'female' else male}, {props}, {STYLE}"
    url = f"https://image.pollinations.ai/prompt/{quote(prompt)}"
    for attempt in range(6):
        try:
            r = requests.get(url, params={"width": 768, "height": 768, "seed": seed, "nologo": "true", "model": "flux"}, timeout=180)
            r.raise_for_status()
            img = crop_watermark(Image.open(io.BytesIO(r.content)).convert("RGB")).resize((SIZE, SIZE), Image.LANCZOS)
            OUT.mkdir(parents=True, exist_ok=True)
            img.save(OUT / f"{figure}.webp", "WEBP", quality=82, method=6)
            print(f"ok {figure} ({(OUT / f'{figure}.webp').stat().st_size // 1024} KB)", flush=True)
            return
        except Exception as exc:  # Pollinations is free and occasionally slow: back off and retry
            print(f"retry {figure}: {exc}", flush=True)
            time.sleep(20 * (attempt + 1))
    print(f"FAILED {figure}", flush=True)


if __name__ == "__main__":
    wanted = sys.argv[1:] or [f for f in FIGURES if not (OUT / f"{f}.webp").exists()]
    for index, name in enumerate(FIGURES):
        if name in wanted:
            render(name, seed=4300 + index)
