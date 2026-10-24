"""Turns a generated picture into a finished ad: headline, call-to-action button
and brand colour laid over the image (src/capabilities/creative.py).

Image models draw text badly, so the visual is generated text-free and the
words are set here, in the site's display face (Fraunces, frontend/public/fonts).
Pillow here has no complex-script shaping (raqm), so text in scripts Fraunces
can't set (Devanagari, Arabic, CJK, emoji...) is left off rather than drawn as
boxes: the picture is still cropped and returned.

Each of the bandit's image styles (src/tools/bandit.py IMAGE_STYLES) has its
own layout, so the bandit's reward also learns which layout works. Layouts
only arrange the campaign's own words: none adds ratings, deadlines or other
claims the brand hasn't made.
"""
import io
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("tools.ad_composer")

FONT_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "fonts"
FONT_PATH = FONT_DIR / "fraunces-var.ttf"
ITALIC_FONT_PATH = FONT_DIR / "fraunces-italic-var.ttf"
DEFAULT_BRAND_COLOR = "#ff6b3d"  # the site accent, also the brand-kit picker's default
SIZES = {"square": (1080, 1080), "banner": (1200, 628)}

HEADLINE_MAX_LINES = 3
HEADLINE_MAX_CHARS = 90
CTA_MAX_CHARS = 28

INK = (17, 19, 22)
WHITE = (255, 255, 255)
PAPER = (247, 245, 240)  # the minimalist band: warm off-white

# Latin (incl. accents for es/fr/pt), general punctuation and currency signs.
_SETTABLE = re.compile(r"^[ -ɏ‐-‧‰-⁞₠-⃏]*$")


def can_set(text: str) -> bool:
    return bool(_SETTABLE.match(text))


@lru_cache(maxsize=64)
def _font(size: int, weight: str = "Bold", italic: bool = False) -> ImageFont.FreeTypeFont:
    try:
        font = ImageFont.truetype(str(ITALIC_FONT_PATH if italic else FONT_PATH), size)
        font.set_variation_by_name(f"{weight} Italic" if italic and weight != "Regular" else ("Italic" if italic else weight))
        return font
    except Exception:  # missing font file or no variation support: Pillow's own face
        return ImageFont.load_default(size)


def _rgb(hex_color: str | None) -> tuple[int, int, int]:
    value = (hex_color or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return _rgb(DEFAULT_BRAND_COLOR)


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ink_on(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Near-black or white, whichever reads better on the given fill."""
    return INK if _luminance(rgb) > 0.22 else WHITE


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Scale to fill `size`, cropping the overflow (centred, a little high so heads survive)."""
    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize((max(w, round(image.width * scale)), max(h, round(image.height * scale))), Image.LANCZOS)
    left = (resized.width - w) // 2
    top = int((resized.height - h) * 0.35)
    return resized.crop((left, top, left + w, top + h))


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if not line or draw.textlength(candidate, font=font) <= max_width:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


@dataclass
class _Text:
    """A headline fitted to a width: its font, lines and total height."""

    font: ImageFont.FreeTypeFont | None
    lines: list[str]
    size: int

    @property
    def gap(self) -> int:
        return round(self.size * 0.12)

    @property
    def height(self) -> int:
        return len(self.lines) * self.size + max(0, len(self.lines) - 1) * self.gap

    def draw(self, draw: ImageDraw.ImageDraw, x: float, y: float, fill, *, align: str = "left", stroke=None) -> float:
        """Draw from top-left (or top-centre for align="center"); returns the y below the block."""
        for line in self.lines:
            anchor = "ma" if align == "center" else "la"
            if stroke:
                draw.text((x, y), line, font=self.font, fill=fill, anchor=anchor, stroke_width=stroke[0], stroke_fill=stroke[1])
            else:
                draw.text((x, y), line, font=self.font, fill=fill, anchor=anchor)
            y += self.size + self.gap
        return y - (self.gap if self.lines else 0)


def _fit(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, floor: int, *, weight="Bold", italic=False) -> _Text:
    """Largest size (start..floor) at which the text fits in HEADLINE_MAX_LINES."""
    if not text:
        return _Text(None, [], 0)
    size = start
    while True:
        font = _font(size, weight, italic)
        lines = _wrap(draw, text, font, max_width)
        fits = len(lines) <= HEADLINE_MAX_LINES and all(draw.textlength(line, font=font) <= max_width for line in lines)
        if fits or size <= floor:
            return _Text(font, _balance(draw, text, font, max_width, lines)[:HEADLINE_MAX_LINES], size)
        size -= 4


def _balance(draw, text: str, font, max_width: int, lines: list[str]) -> list[str]:
    """Even out line lengths (no lone last word): the narrowest width that
    still gives the same number of lines."""
    if len(lines) < 2:
        return lines
    best = lines
    width = max_width
    while width > max_width * 0.5:
        width -= max(4, round(max_width * 0.02))
        attempt = _wrap(draw, text, font, width)
        if len(attempt) != len(lines) or any(draw.textlength(line, font=font) > width for line in attempt):
            break
        best = attempt
    return best


@dataclass
class _Ctx:
    canvas: Image.Image
    headline: str
    cta: str
    brand: tuple[int, int, int]

    @property
    def width(self) -> int:
        return self.canvas.width

    @property
    def height(self) -> int:
        return self.canvas.height

    @property
    def unit(self) -> int:
        return min(self.width, self.height)

    @property
    def margin(self) -> int:
        return round(self.unit * 0.065)


def _button_size(ctx: _Ctx, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    if not ctx.cta:
        return (0, 0)
    left, top, right, bottom = font.getbbox(ctx.cta)
    return (right - left + 2 * round(ctx.unit * 0.036), bottom - top + 2 * round(ctx.unit * 0.022))


def _button(draw, ctx: _Ctx, font, x: float, y: float, fill, ink, *, outline=None) -> None:
    w, h = _button_size(ctx, font)
    if not w:
        return
    if outline:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, outline=outline, width=max(2, round(ctx.unit * 0.003)))
    else:
        draw.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=fill)
    draw.text((x + w / 2, y + h / 2), ctx.cta, font=font, fill=ink, anchor="mm")


def _fade(ctx: _Ctx, height: int, *, from_bottom: bool = True, strength: int = 215) -> None:
    """A dark gradient over the picture so white type stays legible on any image."""
    height = max(1, min(ctx.height, height))
    mask = Image.new("L", (1, height))
    for y in range(height):
        t = y / max(1, height - 1)
        mask.putpixel((0, y), round(strength * (t if from_bottom else 1 - t) ** 1.6))
    shade = Image.new("RGBA", (ctx.width, height), (8, 9, 12, 255))
    shade.putalpha(mask.resize((ctx.width, height)))
    ctx.canvas.alpha_composite(shade, (0, ctx.height - height if from_bottom else 0))


def _lifestyle(ctx: _Ctx) -> Image.Image:
    """Soft dark fade at the bottom, elegant white headline, pill in the brand colour."""
    draw = ImageDraw.Draw(ctx.canvas)
    m = ctx.margin
    text = _fit(draw, ctx.headline, ctx.width - 2 * m, round(ctx.unit * 0.085), round(ctx.unit * 0.05))
    cta_font = _font(round(ctx.unit * 0.036), "SemiBold")
    bh = _button_size(ctx, cta_font)[1]
    gap = round(ctx.unit * 0.035) if text.lines and ctx.cta else 0
    block = text.height + gap + bh
    _fade(ctx, block + 2 * m + round(ctx.unit * 0.18))
    draw = ImageDraw.Draw(ctx.canvas)
    y = text.draw(draw, m, ctx.height - m - block, WHITE)
    _button(draw, ctx, cta_font, m, y + gap if text.lines else y, ctx.brand, _ink_on(ctx.brand))
    return ctx.canvas


def _minimalist(ctx: _Ctx, picture: Image.Image) -> Image.Image:
    """A calm off-white band on top with dark, lighter-weight type and an
    outlined button; the picture fills the rest, untouched by any fade."""
    probe = ImageDraw.Draw(ctx.canvas)
    m = ctx.margin
    text = _fit(probe, ctx.headline, ctx.width - 2 * m, round(ctx.unit * 0.068), round(ctx.unit * 0.042), weight="Regular")
    cta_font = _font(round(ctx.unit * 0.032), "SemiBold")
    bh = _button_size(ctx, cta_font)[1]
    gap = round(ctx.unit * 0.03) if text.lines and ctx.cta else 0
    band = min(round(ctx.height * 0.5), text.height + gap + bh + 2 * m)
    canvas = Image.new("RGBA", (ctx.width, ctx.height), PAPER + (255,))
    canvas.paste(_cover(picture, (ctx.width, ctx.height - band)).convert("RGBA"), (0, band))
    draw = ImageDraw.Draw(canvas)
    y = text.draw(draw, m, m, INK)
    _button(draw, ctx, cta_font, m, y + gap if text.lines else y, None, INK, outline=INK)
    # A short rule in the brand colour where band meets picture.
    rule = max(4, round(ctx.unit * 0.006))
    draw.rectangle((m, band - rule, m + round(ctx.unit * 0.12), band), fill=ctx.brand)
    return canvas


def _testimonial(ctx: _Ctx) -> Image.Image:
    """The headline as a quote: a large opening quote mark in the brand
    colour above italic type, on the bottom fade. No stars or attribution,
    since those would claim reviews the brand hasn't shown."""
    draw = ImageDraw.Draw(ctx.canvas)
    m = ctx.margin
    text = _fit(draw, ctx.headline, ctx.width - 2 * m, round(ctx.unit * 0.075), round(ctx.unit * 0.045), weight="SemiBold", italic=True)
    mark_font = _font(round(ctx.unit * 0.2), "Black")
    mark_h = round(ctx.unit * 0.1) if text.lines else 0
    cta_font = _font(round(ctx.unit * 0.034), "SemiBold")
    bh = _button_size(ctx, cta_font)[1]
    gap = round(ctx.unit * 0.04) if text.lines and ctx.cta else 0
    block = mark_h + text.height + gap + bh
    _fade(ctx, block + 2 * m + round(ctx.unit * 0.2), strength=225)
    draw = ImageDraw.Draw(ctx.canvas)
    top = ctx.height - m - block
    if text.lines:
        draw.text((m - round(ctx.unit * 0.008), top - round(ctx.unit * 0.04)), "“", font=mark_font, fill=ctx.brand, anchor="la")
    y = text.draw(draw, m, top + mark_h, WHITE)
    _button(draw, ctx, cta_font, m, y + gap if text.lines else y, WHITE, INK)
    return ctx.canvas


def _humor(ctx: _Ctx) -> Image.Image:
    """Meme-style: a big heavy caption centred across the top with a dark
    outline (readable on any picture, no fade), plain white button below."""
    draw = ImageDraw.Draw(ctx.canvas)
    m = ctx.margin
    text = _fit(draw, ctx.headline, ctx.width - 2 * m, round(ctx.unit * 0.1), round(ctx.unit * 0.055), weight="Black")
    stroke = (max(3, round(text.size * 0.08)), INK) if text.lines else None
    text.draw(draw, ctx.width / 2, m, WHITE, align="center", stroke=stroke)
    cta_font = _font(round(ctx.unit * 0.036), "Bold")
    bw, bh = _button_size(ctx, cta_font)
    if bw:
        # A soft shadow so the white pill lifts off light pictures too.
        shadow = Image.new("RGBA", ctx.canvas.size, (0, 0, 0, 0))
        x, y = (ctx.width - bw) / 2, ctx.height - m - bh
        ImageDraw.Draw(shadow).rounded_rectangle((x, y + 6, x + bw, y + bh + 6), radius=bh // 2, fill=(0, 0, 0, 110))
        ctx.canvas.alpha_composite(shadow)
        _button(ImageDraw.Draw(ctx.canvas), ctx, cta_font, x, y, WHITE, INK)
    return ctx.canvas


def _urgency(ctx: _Ctx) -> Image.Image:
    """High energy: a solid band in the brand colour across the bottom with
    heavy type, and a dark button. No invented deadline or "limited" tag."""
    draw = ImageDraw.Draw(ctx.canvas)
    m = ctx.margin
    text = _fit(draw, ctx.headline, ctx.width - 2 * m, round(ctx.unit * 0.08), round(ctx.unit * 0.048), weight="Black")
    cta_font = _font(round(ctx.unit * 0.036), "Bold")
    bh = _button_size(ctx, cta_font)[1]
    gap = round(ctx.unit * 0.03) if text.lines and ctx.cta else 0
    pad = round(m * 0.8)
    band = text.height + gap + bh + 2 * pad
    top = ctx.height - band
    ink = _ink_on(ctx.brand)
    # A slanted top edge reads as motion.
    slant = round(ctx.unit * 0.05)
    draw.polygon([(0, top), (ctx.width, top - slant), (ctx.width, ctx.height), (0, ctx.height)], fill=ctx.brand)
    y = text.draw(draw, m, top + pad, ink)
    button_fill = INK if ink == WHITE or _luminance(ctx.brand) > 0.22 else WHITE
    _button(draw, ctx, cta_font, m, y + gap if text.lines else y, button_fill, _ink_on(button_fill))
    return ctx.canvas


def _place_logo(canvas: Image.Image, logo: Image.Image, corner: str) -> None:
    """The brand logo, scaled into a small box, on a white rounded chip so any
    logo reads on any picture."""
    unit = min(canvas.size)
    m = round(unit * 0.045)
    pad = round(unit * 0.014)
    logo = logo.convert("RGBA")
    logo.thumbnail((round(unit * 0.2), round(unit * 0.075)), Image.LANCZOS)
    w, h = logo.width + 2 * pad, logo.height + 2 * pad
    x = m if corner.endswith("left") else canvas.width - m - w
    y = m if corner.startswith("top") else canvas.height - m - h
    chip = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle((x, y, x + w, y + h), radius=round(min(w, h) * 0.28), fill=(255, 255, 255, 235))
    canvas.alpha_composite(chip)
    canvas.alpha_composite(logo, (x + pad, y + pad))


# Where each layout's text isn't: the logo goes there.
LOGO_CORNERS = {
    "lifestyle_aspirational": "top-left",
    "minimalist": "bottom-right",
    "testimonial_social_proof": "top-left",
    "humor_meme": "bottom-right",
    "urgency_scarcity": "top-left",
}

LAYOUTS: dict[str, Callable[..., Image.Image]] = {
    "lifestyle_aspirational": _lifestyle,
    "minimalist": _minimalist,
    "testimonial_social_proof": _testimonial,
    "humor_meme": _humor,
    "urgency_scarcity": _urgency,
}
DEFAULT_LAYOUT = "lifestyle_aspirational"


def compose_ad(
    image_bytes: bytes,
    headline: str = "",
    cta: str = "",
    *,
    brand_color: str | None = None,
    fmt: str = "square",
    style: str | None = None,
    logo_bytes: bytes | None = None,
) -> bytes:
    """The finished ad as JPEG bytes, laid out for the image style (unknown
    styles get the lifestyle layout). Headline and CTA are optional; text the
    font can't set is skipped (see the module docstring). The brand logo, if
    given and readable, goes in the corner the layout leaves free."""
    width, height = SIZES[fmt]
    picture = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    canvas = _cover(picture, (width, height)).convert("RGBA")

    headline = _clip(headline, HEADLINE_MAX_CHARS)
    cta = _clip(cta, CTA_MAX_CHARS)
    if headline and not can_set(headline):
        logger.info("headline left off: script not settable without shaping")
        headline = ""
    if cta and not can_set(cta):
        cta = ""
    name = style if style in LAYOUTS else DEFAULT_LAYOUT
    if headline or cta:
        ctx = _Ctx(canvas, headline, cta, _rgb(brand_color))
        canvas = _minimalist(ctx, picture) if name == "minimalist" else LAYOUTS[name](ctx)
    logo = _open_logo(logo_bytes)
    if logo is not None:
        _place_logo(canvas, logo, LOGO_CORNERS[name])
    return _jpeg(canvas)


def _open_logo(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        return Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        logger.warning("brand logo unreadable, left off")
        return None


def _jpeg(image: Image.Image) -> bytes:
    # JPEG, not PNG: a 1080px photo as PNG can pass Bluesky's ~1 MB image cap.
    out = io.BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=88, optimize=True, progressive=True)
    return out.getvalue()
