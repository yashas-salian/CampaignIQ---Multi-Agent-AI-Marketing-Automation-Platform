"""Render the ad template previews (frontend/public/templates/<template>.webp).

The Tools page's template gallery shows every template with the same sample
product, so people can compare layouts side by side. Each preview is a real
render from src/tools/ad_templates.py, cut out the same way the app does it.
No image model is called: the 8 scene templates draw their own fallback
background, and the gallery says that in real use the AI paints a scene.

    python frontend/scripts/render_template_previews.py <product photo>
"""
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.tools.ad_templates import TEMPLATES, Slots, compose_product_ad  # noqa: E402
from src.tools.product_cutout import cutout  # noqa: E402

OUT = ROOT / "frontend" / "public" / "templates"
SIDE = 480

# The fictional brand from the README screenshots.
SLOTS = Slots(
    headline="Instant Hydration with Electrolytes",
    cta="Drink Now",
    tagline="Piyo aur pine do",
    eyebrow="New launch",
    big_word="HYDRATE",
    benefits=["Electrolyte boost", "Mineral recharge", "Great hydration"],
    steps=["Chill the bottle", "Shake it up", "Sip and recharge"],
    stat="0g sugar",
    badge="NEW",
)
BRAND_COLOR = "#2E2A8C"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    product = cutout(Path(sys.argv[1]).read_bytes())
    OUT.mkdir(parents=True, exist_ok=True)
    for template in TEMPLATES:
        jpeg = compose_product_ad(product, template, SLOTS, brand_color=BRAND_COLOR)
        image = Image.open(io.BytesIO(jpeg)).resize((SIDE, SIDE), Image.LANCZOS)
        image.save(OUT / f"{template}.webp", "WEBP", quality=80, method=6)
        print(template)


if __name__ == "__main__":
    main()
