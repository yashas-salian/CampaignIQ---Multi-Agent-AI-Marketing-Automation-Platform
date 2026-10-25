"""Product-first ad templates: the campaign's real product photo (cut out by
src/tools/product_cutout.py) set into one of 34 layouts drawn from real
industry ads (docs/AD_TEMPLATES.md has the research and sources).

The product is always the hero and is never repainted by an image model. Most
templates draw their whole background here (gradients, rings, podiums,
starbursts...), so they need no image generation at all; the few marked
`scene` place the product into a background the image model painted with an
empty spot for it (and fall back to a drawn gradient if there is none).

Templates belong to the bandit's five image styles (src/tools/bandit.py
IMAGE_STYLES), so the bandit still learns which style works; the creative
step picks the template within the style that suits the product.

Layout rules from the research, applied by every template: 1080 square, a
64px safe margin, one hero product, at most two type families, headline set
large and short, one call-to-action pill, the logo small, at most one badge.
Templates only arrange the campaign's own words: none adds ratings,
reviews, numbers, deadlines or discounts the brand hasn't stated.
"""
import io
import logging
import math
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from src.tools.ad_composer import FONT_DIR, INK, WHITE, _balance, _clip, _cover, _jpeg, _luminance, _open_logo, _rgb, _wrap, can_set

logger = logging.getLogger("tools.ad_templates")

SIZE = 1080
M = 64  # safe margin
CTA_MAX_CHARS = 24
HEADLINE_MAX_CHARS = 60

FACE_FILES = {
    "display": ("anton-regular.ttf", None),  # condensed poster sans
    "sans": ("montserrat-var.ttf", "Bold"),  # geometric sans
    "serif": ("fraunces-var.ttf", "SemiBold"),
    "italic": ("fraunces-italic-var.ttf", "SemiBold Italic"),
    "script": ("pacifico-regular.ttf", None),
    "hand": ("caveat-var.ttf", "Bold"),
}
# Line spacing per face, as a share of the size (script faces have tall ascenders).
LEADING = {"display": 1.02, "sans": 1.12, "serif": 1.1, "italic": 1.1, "script": 1.35, "hand": 1.0}


@lru_cache(maxsize=256)
def face(kind: str, size: int, weight: str | None = None) -> ImageFont.FreeTypeFont:
    file, default = FACE_FILES.get(kind, FACE_FILES["sans"])
    try:
        font = ImageFont.truetype(str(FONT_DIR / file), size)
        style = weight or default
        if style:
            if kind == "italic" and "Italic" not in style:
                style = "Italic" if style == "Regular" else f"{style} Italic"
            try:
                font.set_variation_by_name(style)
            except Exception:
                pass
        return font
    except Exception:  # missing font file: Pillow's own face
        return ImageFont.load_default(size)


# ---------------------------------------------------------------- slots


@dataclass
class Slots:
    """The words on an ad. Everything is optional; templates leave out what's empty."""

    headline: str = ""
    cta: str = ""
    tagline: str = ""
    eyebrow: str = ""
    big_word: str = ""
    benefits: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    stat: str = ""
    badge: str = ""

    @classmethod
    def from_dict(cls, data: dict | None) -> "Slots":
        data = data or {}

        def line(key: str, limit: int) -> str:
            text = _clip(str(data.get(key) or ""), limit)
            return text if text and can_set(text) else ""

        def items(key: str, limit: int, count: int = 3) -> list[str]:
            raw = data.get(key) or []
            raw = raw if isinstance(raw, list) else [raw]
            out = [_clip(str(v), limit) for v in raw if str(v or "").strip()]
            return [v for v in out if can_set(v)][:count]

        return cls(
            headline=line("headline", HEADLINE_MAX_CHARS),
            cta=line("cta", CTA_MAX_CHARS),
            tagline=line("tagline", 80),
            eyebrow=line("eyebrow", 32),
            big_word=line("big_word", 14).split(" ")[0] if line("big_word", 14) else "",
            benefits=items("benefits", 30),
            steps=items("steps", 34),
            stat=line("stat", 8),
            badge=line("badge", 14),
        )

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v}


# ---------------------------------------------------------------- colour


def mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(x + (y - x) * t) for x, y in zip(a[:3], b[:3]))  # type: ignore[return-value]


def ink_on(rgb) -> tuple[int, int, int]:
    return INK if _luminance(rgb) > 0.22 else WHITE


@dataclass
class Palette:
    brand: tuple[int, int, int]

    @property
    def light(self):
        return mix(self.brand, WHITE, 0.86)

    @property
    def soft(self):
        return mix(self.brand, WHITE, 0.6)

    @property
    def dark(self):
        return mix(self.brand, (0, 0, 0), 0.55)

    @property
    def deep(self):
        return mix(self.brand, (8, 9, 14), 0.85)

    @property
    def accent(self):
        """A pop colour for CTAs and stickers that stands apart from the brand colour."""
        r, g, b = self.brand
        yellowish = r > 180 and g > 150 and b < 120
        return (24, 24, 28) if yellowish else (255, 204, 41)


# ---------------------------------------------------------------- the ad being drawn


@dataclass
class Ad:
    canvas: Image.Image
    product: Image.Image
    slots: Slots
    palette: Palette
    scene: Image.Image | None = None
    logo: Image.Image | None = None
    seed: int = 0
    text_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)  # foreground words and buttons
    product_box: tuple[int, int, int, int] | None = None

    @property
    def draw(self) -> ImageDraw.ImageDraw:
        return ImageDraw.Draw(self.canvas)

    @property
    def rng(self) -> random.Random:
        return random.Random(self.seed * 7919 + 17)

    @property
    def variant(self) -> int:
        return self.seed % 3


# ---------------------------------------------------------------- backgrounds


def fill(ad: Ad, color) -> None:
    ad.canvas.paste(color + (255,), (0, 0, SIZE, SIZE))


def vgradient(ad: Ad, top, bottom, box=None) -> None:
    x0, y0, x1, y1 = box or (0, 0, SIZE, SIZE)
    h = max(1, y1 - y0)
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        strip.putpixel((0, y), mix(top, bottom, y / max(1, h - 1)))
    ad.canvas.paste(strip.resize((x1 - x0, h)), (x0, y0))


def radial(ad: Ad, inner, outer, center=(0.5, 0.45), radius=0.75) -> None:
    """A soft radial gradient: `inner` at the centre fading to `outer`."""
    mask = Image.radial_gradient("L").resize((round(SIZE * radius * 2),) * 2)  # 0 centre -> 255 edge
    base = Image.new("RGB", (SIZE, SIZE), outer)
    glow = Image.new("RGB", mask.size, inner)
    cx, cy = round(SIZE * center[0] - mask.width / 2), round(SIZE * center[1] - mask.height / 2)
    base.paste(glow, (cx, cy), ImageOps.invert(mask))
    ad.canvas.paste(base, (0, 0))


def rings(ad: Ad, colors, center=(0.5, 0.52), step=110) -> None:
    d = ad.draw
    cx, cy = SIZE * center[0], SIZE * center[1]
    r = SIZE * 1.1
    i = 0
    while r > step * 0.6:
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colors[i % len(colors)])
        r -= step
        i += 1


def rays(ad: Ad, a, b, center=(0.5, 0.55), count=24) -> None:
    fill(ad, a)
    d = ad.draw
    cx, cy = SIZE * center[0], SIZE * center[1]
    for i in range(count):
        if i % 2:
            continue
        t0, t1 = 2 * math.pi * i / count, 2 * math.pi * (i + 1) / count
        d.polygon([(cx, cy), (cx + 2000 * math.cos(t0), cy + 2000 * math.sin(t0)), (cx + 2000 * math.cos(t1), cy + 2000 * math.sin(t1))], fill=b)


def halftone(ad: Ad, color, box=None, spacing=34, max_r=9, fade_down=True) -> None:
    x0, y0, x1, y1 = box or (0, 0, SIZE, SIZE)
    d = ad.draw
    for row, y in enumerate(range(y0, y1, spacing)):
        t = (y - y0) / max(1, y1 - y0)
        r = max_r * (1 - t if fade_down else t)
        if r < 1.2:
            continue
        for x in range(x0 + (spacing // 2 if row % 2 else 0), x1, spacing):
            d.ellipse((x - r, y - r, x + r, y + r), fill=color)


def blob(ad: Ad, center, radius, color, points=9, jitter=0.28) -> None:
    rng = ad.rng
    pts = []
    for i in range(points):
        a = 2 * math.pi * i / points
        r = radius * (1 + rng.uniform(-jitter, jitter))
        pts.append((center[0] + r * math.cos(a), center[1] + r * math.sin(a)))
    for _ in range(4):  # Chaikin smoothing
        smooth = []
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            smooth += [(0.75 * p[0] + 0.25 * q[0], 0.75 * p[1] + 0.25 * q[1]), (0.25 * p[0] + 0.75 * q[0], 0.25 * p[1] + 0.75 * q[1])]
        pts = smooth
    ad.draw.polygon(pts, fill=color)


def paper(ad: Ad, color) -> None:
    fill(ad, color)
    noise = Image.effect_noise((SIZE // 2, SIZE // 2), 28).resize((SIZE, SIZE)).convert("RGB")
    ad.canvas.paste(Image.blend(ad.canvas.convert("RGB"), ImageChops.multiply(ad.canvas.convert("RGB"), noise.point(lambda v: 200 + v // 5)), 0.6), (0, 0))


def scene_or(ad: Ad, fallback: Callable[[], None]) -> bool:
    """Paint the image model's scene full-bleed; without one, draw the fallback."""
    if ad.scene is not None:
        ad.canvas.paste(_cover(ad.scene, (SIZE, SIZE)).convert("RGBA"), (0, 0))
        return True
    fallback()
    return False


def scrim(ad: Ad, box, color=(8, 9, 12), strength=190, direction="up") -> None:
    """A gradient over part of the picture so the words on it stay legible."""
    x0, y0, x1, y1 = box
    h = max(1, y1 - y0)
    mask = Image.new("L", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        mask.putpixel((0, y), round(strength * ((t if direction == "up" else 1 - t) ** 1.4)))
    layer = Image.new("RGBA", (x1 - x0, h), color + (255,))
    layer.putalpha(mask.resize((x1 - x0, h)))
    ad.canvas.alpha_composite(layer, (x0, y0))


def soft_shadow(ad: Ad, box, radius=30, opacity=90, blur=28, offset=(0, 18)) -> None:
    layer = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle((x0 + offset[0], y0 + offset[1], x1 + offset[0], y1 + offset[1]), radius=radius, fill=(0, 0, 0, opacity))
    ad.canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


# ---------------------------------------------------------------- the product


def place(
    ad: Ad, box, *, align="bottom", tilt: float = 0, shadow: str | None = "floor", reflection=False,
    outline: int = 0, product: Image.Image | None = None, grow: bool = False,
) -> tuple[int, int, int, int]:
    """Fit the product into `box` (keeping its shape), with an optional tilt,
    floor or drop shadow, mirror reflection or white sticker outline. With
    `grow`, a wide product (a shoe, headphones) may widen a narrow box
    symmetrically up to the margins, so it isn't shrunk to a sliver."""
    x0, y0, x1, y1 = (round(v) for v in box)
    item = (product or ad.product).copy()
    if grow and item.width / item.height > (x1 - x0) / max(1, y1 - y0):
        cx = (x0 + x1) / 2
        half = min(cx - M, SIZE - M - cx, (y1 - y0) * item.width / item.height * 0.42)
        x0, x1 = round(min(x0, cx - half)), round(max(x1, cx + half))
    if outline:
        alpha = item.getchannel("A").point(lambda v: 255 if v > 40 else 0)
        pad = outline + 2
        grown = ImageOps.expand(alpha, border=pad, fill=0).filter(ImageFilter.MaxFilter(outline * 2 + 1)).filter(ImageFilter.GaussianBlur(1))
        sticker = Image.new("RGBA", grown.size, WHITE + (0,))
        sticker.putalpha(grown)
        sticker.alpha_composite(item, (pad, pad))
        item = sticker
    if tilt:
        item = item.rotate(tilt, resample=Image.BICUBIC, expand=True)
        item = item.crop(item.getchannel("A").getbbox() or (0, 0, item.width, item.height))
    scale = min((x1 - x0) / item.width, (y1 - y0) / item.height)
    item = item.resize((max(1, round(item.width * scale)), max(1, round(item.height * scale))), Image.LANCZOS)
    px = x0 + ((x1 - x0) - item.width) // 2
    py = y1 - item.height if align == "bottom" else (y0 + ((y1 - y0) - item.height) // 2 if align == "center" else y0)
    if shadow == "floor":
        layer = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
        w = item.width * 0.42
        cy = py + item.height - 4
        ImageDraw.Draw(layer).ellipse((px + item.width / 2 - w, cy - 14, px + item.width / 2 + w, cy + 16), fill=(0, 0, 0, 120))
        ad.canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(16)))
    elif shadow == "drop":
        silhouette = Image.new("RGBA", item.size, (0, 0, 0, 0))
        silhouette.putalpha(item.getchannel("A").point(lambda v: v * 95 // 255))
        layer = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
        layer.alpha_composite(silhouette, (px + 22, py + 30))
        ad.canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(18)))
    if reflection:
        mirror = ImageOps.flip(item)
        fade = Image.linear_gradient("L").resize(mirror.size)  # 0 top -> 255 bottom
        alpha = ImageChops.multiply(mirror.getchannel("A"), ImageOps.invert(fade).point(lambda v: v * 70 // 255))
        mirror.putalpha(alpha)
        ad.canvas.alpha_composite(mirror, (px, py + item.height + 2))
    ad.canvas.alpha_composite(item, (px, py))
    ad.product_box = (px, py, px + item.width, py + item.height)
    return ad.product_box


# ---------------------------------------------------------------- words


@dataclass
class Fitted:
    font: ImageFont.FreeTypeFont | None
    lines: list[str]
    size: int
    leading: float

    @property
    def line_h(self) -> int:
        return round(self.size * self.leading)

    @property
    def cap(self) -> int:
        """Height of a capital above the baseline: blocks are measured from the
        visible top of the letters, not the font's (much taller) ascender."""
        return -self.font.getbbox("H", anchor="ls")[1] if self.font else 0

    @property
    def descent(self) -> int:
        return round(self.size * 0.22)

    @property
    def height(self) -> int:
        if not self.lines:
            return 0
        return self.cap + (len(self.lines) - 1) * self.line_h + self.descent

    def width(self, draw) -> int:
        return max((round(draw.textlength(line, font=self.font)) for line in self.lines), default=0)

    def draw_lines(self, draw, x: float, y: float, fill_color, *, align="left", stroke=None) -> list[tuple[int, int, int, int]]:
        """Draw from the block's visible top; returns each line's box."""
        anchor = {"left": "ls", "center": "ms", "right": "rs"}[align]
        boxes = []
        base = y + self.cap
        for line in self.lines:
            kw = {"stroke_width": stroke[0], "stroke_fill": stroke[1]} if stroke else {}
            draw.text((x, base), line, font=self.font, fill=fill_color, anchor=anchor, **kw)
            w = draw.textlength(line, font=self.font)
            left = x if align == "left" else (x - w / 2 if align == "center" else x - w)
            boxes.append((round(left), round(base - self.cap), round(left + w), round(base + self.descent)))
            base += self.line_h
        return boxes


def fit(draw, text: str, kind: str, max_w: int, start: int, floor: int, *, weight=None, lines=3, upper=False) -> Fitted:
    text = (text or "").upper() if upper else (text or "")
    if not text:
        return Fitted(None, [], 0, 1)
    size = start
    while True:
        font = face(kind, size, weight)
        wrapped = _wrap(draw, text, font, max_w)
        ok = len(wrapped) <= lines and all(draw.textlength(line, font=font) <= max_w for line in wrapped)
        if ok:
            return Fitted(font, _balance(draw, text, font, max_w, wrapped)[:lines], size, LEADING.get(kind, 1.12))
        if size <= floor:
            kept = wrapped[:lines]
            if len(wrapped) > lines:
                last = kept[-1]
                while last and draw.textlength(last + "…", font=font) > max_w:
                    last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
                kept[-1] = last.rstrip(" ,;:-") + "…"
            return Fitted(font, kept, size, LEADING.get(kind, 1.12))
        size -= 4


def write(ad: Ad, block: Fitted, x: float, y: float, fill_color, *, align="left", stroke=None, record=True, layer=None) -> int:
    """Draw a fitted block from its top; returns the y below it."""
    draw = ImageDraw.Draw(layer) if layer is not None else ad.draw
    if not block.lines:
        return round(y)
    boxes = block.draw_lines(draw, x, y, fill_color, align=align, stroke=stroke)
    if record:
        ad.text_boxes.extend(boxes)
    return round(y + block.height)


def text(ad: Ad, value: str, kind: str, x, y, max_w, start, floor, color, *, weight=None, lines=3, upper=False, align="left", stroke=None) -> int:
    if not value:
        return round(y)
    return write(ad, fit(ad.draw, value, kind, max_w, start, floor, weight=weight, lines=lines, upper=upper), x, y, color, align=align, stroke=stroke)


def tracked(ad: Ad, value: str, x, y, size, color, *, align="left", spacing=0.18, weight="SemiBold") -> int:
    """A small caps label with letter spacing (eyebrows, tags)."""
    if not value:
        return round(y)
    value = value.upper()
    font = face("sans", size, weight)
    gap = size * spacing
    total = sum(ad.draw.textlength(ch, font=font) for ch in value) + gap * (len(value) - 1)
    cx = x if align == "left" else (x - total / 2 if align == "center" else x - total)
    left = cx
    for ch in value:
        ad.draw.text((cx, y), ch, font=font, fill=color, anchor="la")
        cx += ad.draw.textlength(ch, font=font) + gap
    ad.text_boxes.append((round(left), round(y), round(left + total), round(y + size)))
    return round(y + size * 1.3)


def pill(ad: Ad, label: str, x, y, fill_color, ink=None, *, size=36, align="left", outline=None, kind="sans") -> tuple[int, int, int, int] | None:
    if not label:
        return None
    font = face(kind, size, "Bold" if kind == "sans" else None)
    l, t, r, b = font.getbbox(label)
    w, h = r - l + 2 * round(size * 1.05), b - t + 2 * round(size * 0.62)
    x = x if align == "left" else (x - w / 2 if align == "center" else x - w)
    box = (round(x), round(y), round(x + w), round(y + h))
    d = ad.draw
    if outline:
        d.rounded_rectangle(box, radius=h // 2, outline=outline, width=4)
    else:
        d.rounded_rectangle(box, radius=h // 2, fill=fill_color)
    d.text((x + w / 2, y + h / 2), label, font=font, fill=ink or ink_on(fill_color or WHITE), anchor="mm")
    ad.text_boxes.append(box)
    return box


def pill_size(label: str, size=36) -> tuple[int, int]:
    if not label:
        return (0, 0)
    font = face("sans", size, "Bold")
    l, t, r, b = font.getbbox(label)
    return r - l + 2 * round(size * 1.05), b - t + 2 * round(size * 0.62)


def logo(ad: Ad, where: str = "top-left") -> None:
    """The brand logo, small, on a white chip, in a corner or centred at the top/bottom."""
    if ad.logo is None:
        return
    item = ad.logo.copy()
    item.thumbnail((round(SIZE * 0.17), round(SIZE * 0.06)), Image.LANCZOS)
    pad = 14
    w, h = item.width + 2 * pad, item.height + 2 * pad
    vert, horiz = where.split("-")
    x = {"left": M - 8, "right": SIZE - M + 8 - w, "center": (SIZE - w) // 2}[horiz]
    y = M - 16 if vert == "top" else SIZE - M + 16 - h
    chip = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(chip).rounded_rectangle((x, y, x + w, y + h), radius=round(min(w, h) * 0.28), fill=(255, 255, 255, 238))
    ad.canvas.alpha_composite(chip)
    ad.canvas.alpha_composite(item, (x + pad, y + pad))


LOGO_ROW = 120  # height a top logo chip takes, so headlines start below it


def check_icon(ad: Ad, x, y, size, color, ok=True) -> None:
    d = ad.draw
    d.ellipse((x, y, x + size, y + size), fill=color)
    ink = ink_on(color)
    s = size
    if ok:
        d.line([(x + s * 0.27, y + s * 0.52), (x + s * 0.44, y + s * 0.68), (x + s * 0.74, y + s * 0.34)], fill=ink, width=max(3, round(s * 0.11)), joint="curve")
    else:
        w = max(3, round(s * 0.1))
        d.line([(x + s * 0.32, y + s * 0.32), (x + s * 0.68, y + s * 0.68)], fill=ink, width=w)
        d.line([(x + s * 0.68, y + s * 0.32), (x + s * 0.32, y + s * 0.68)], fill=ink, width=w)


def starburst(ad: Ad, center, radius, color, label: str, *, points=20, angle=-12) -> None:
    layer = Image.new("RGBA", (round(radius * 2.4),) * 2, (0, 0, 0, 0))
    c = layer.width / 2
    pts = []
    for i in range(points * 2):
        r = radius if i % 2 == 0 else radius * 0.82
        a = math.pi * i / points
        pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    d = ImageDraw.Draw(layer)
    d.polygon(pts, fill=color)
    ink = ink_on(color)
    block = fit(d, label.upper(), "display", round(radius * 1.25), round(radius * 0.55), round(radius * 0.22), lines=2)
    block.draw_lines(d, c, c - (block.height - block.descent) / 2, ink, align="center")
    layer = layer.rotate(-angle, resample=Image.BICUBIC)
    ad.canvas.alpha_composite(layer, (round(center[0] - c), round(center[1] - c)))
    ad.text_boxes.append((round(center[0] - radius), round(center[1] - radius), round(center[0] + radius), round(center[1] + radius)))


def rotated_text(ad: Ad, value: str, kind: str, center, height: int, angle: float, color, *, weight=None, record=False) -> None:
    """One word set at `height` px and turned by `angle` degrees (flanking script words, ribbons)."""
    if not value:
        return
    font = face(kind, height, weight)
    l, t, r, b = font.getbbox(value)
    layer = Image.new("RGBA", (r - l + 40, round((b - t) * 1.6) + 40), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text((layer.width / 2, layer.height / 2), value, font=font, fill=color, anchor="mm")
    layer = layer.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = round(center[0] - layer.width / 2), round(center[1] - layer.height / 2)
    ad.canvas.alpha_composite(layer, (x, y))
    if record:
        box = layer.getchannel("A").getbbox()
        if box:
            ad.text_boxes.append((x + box[0], y + box[1], x + box[2], y + box[3]))


def dashed_curve(ad: Ad, points, color, width=5, dash=18, gap=14) -> None:
    """A dashed quadratic Bezier through three points (doodle paths)."""
    (x0, y0), (cx, cy), (x1, y1) = points
    samples = [((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t * t * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t * t * y1) for t in [i / 200 for i in range(201)]]
    run, on, start = 0.0, True, samples[0]
    d = ad.draw
    for a, b in zip(samples, samples[1:]):
        run += math.dist(a, b)
        if on and run >= dash:
            d.line([start, b], fill=color, width=width)
            run, on, start = 0, False, b
        elif not on and run >= gap:
            run, on, start = 0, True, b


def arrow_head(ad: Ad, tip, angle_deg, color, size=26, width=6) -> None:
    a = math.radians(angle_deg)
    for side in (-0.5, 0.5):
        ad.draw.line([tip, (tip[0] - size * math.cos(a + side), tip[1] - size * math.sin(a + side))], fill=color, width=width)


def sparkle(ad: Ad, center, size, color, width=5) -> None:
    x, y = center
    for i in range(3):
        a = math.radians(-60 + i * 35)
        ad.draw.line([(x + size * 0.35 * math.cos(a), y + size * 0.35 * math.sin(a)), (x + size * math.cos(a), y + size * math.sin(a))], fill=color, width=width)


def is_wide(ad: Ad) -> bool:
    return ad.product.width / ad.product.height > 1.35


def side_box(ad: Ad, col: int, text_bottom: int) -> tuple[int, int, int, int]:
    """Where the product goes beside a left text column: the right column for
    a tall product; for a wide one, a wider band at the bottom right, below the words."""
    if is_wide(ad):
        return (col - 140, max(text_bottom + 30, SIZE - 470), SIZE - M, SIZE - M - 110)
    return (col + 20, 150, SIZE - M, SIZE - M - 20)


def headline_stack(ad: Ad, x, y, max_w, color, *, kind="sans", start=96, floor=56, align="left", upper=False, lines=3, tagline_color=None, weight=None) -> int:
    """Headline, then tagline under it: the usual top-of-ad block."""
    s = ad.slots
    y = text(ad, s.headline, kind, x, y, max_w, start, floor, color, weight=weight, lines=lines, upper=upper, align=align)
    if s.tagline:
        y = text(ad, s.tagline, "sans", x, y + 18, max_w, 40, 32, tagline_color or color, weight="Medium", lines=2, align=align)
    return y


def bottom_cta(ad: Ad, fill_color, *, align="center", x=None, size=38) -> int:
    """The CTA pill on the bottom margin; returns the top of the area it takes."""
    w, h = pill_size(ad.slots.cta, size)
    if not w:
        return SIZE - M
    y = SIZE - M - h
    xx = x if x is not None else (SIZE / 2 if align == "center" else (M if align == "left" else SIZE - M))
    pill(ad, ad.slots.cta, xx, y, fill_color, size=size, align=align)
    return y


# ---------------------------------------------------------------- templates: minimalist


def centered_hero(ad: Ad) -> None:
    p = ad.palette
    top, bottom = [(p.light, p.soft), (WHITE, p.light), (p.soft, p.brand)][ad.variant]
    vgradient(ad, top, bottom)
    ink = ink_on(top)
    y = tracked(ad, ad.slots.eyebrow, SIZE / 2, M, 28, ink, align="center")
    y = headline_stack(ad, SIZE / 2, y + 10 if ad.slots.eyebrow else M, SIZE - 2 * M, ink, align="center", lines=2, start=84, floor=54)
    cta_top = bottom_cta(ad, p.brand if ad.variant != 2 else INK)
    place(ad, (M + 80, y + 40, SIZE - M - 80, cta_top - 36), grow=True)
    logo(ad, "bottom-left")


def icon_on_void(ad: Ad) -> None:
    p = ad.palette
    radial(ad, mix(p.deep, WHITE, 0.16), (6, 6, 9), center=(0.5, 0.42), radius=0.62)
    tag = ad.slots.tagline or ad.slots.headline
    place(ad, (300, 150, SIZE - 300, 700), reflection=True, shadow=None, grow=True)
    y = 800
    y = text(ad, ad.slots.headline if ad.slots.tagline else "", "serif", SIZE / 2, y, SIZE - 2 * M, 64, 44, WHITE, weight="Regular", lines=2, align="center")
    tracked(ad, tag, SIZE / 2, y + 14, 30, mix(WHITE, p.brand, 0.25), align="center", spacing=0.24, weight="Medium")
    logo(ad, "top-center")


def podium_showcase(ad: Ad) -> None:
    p = ad.palette
    bg = [p.light, mix(p.brand, WHITE, 0.75), p.soft][ad.variant]
    fill(ad, bg)
    d = ad.draw
    arch = mix(bg, p.brand, 0.22)
    d.rounded_rectangle((250, 330, 830, 1200), radius=290, fill=arch)
    # The podium: an elliptical top on a shaded cylinder.
    top_y, bot_y, x0, x1 = 840, 990, 230, 850
    body = Image.new("RGB", (x1 - x0, bot_y - top_y))
    for x in range(body.width):
        t = abs(x / body.width - 0.35) * 1.6
        body.paste(mix(WHITE, mix(bg, p.brand, 0.35), min(1, t)), (x, 0, x + 1, body.height))
    ad.canvas.paste(body, (x0, top_y))
    d.ellipse((x0, bot_y - 44, x1, bot_y + 44), fill=mix(bg, p.brand, 0.35))
    d.ellipse((x0, top_y - 44, x1, top_y + 44), fill=mix(WHITE, bg, 0.3))
    d.ellipse((150, 930, 230, 1010), fill=mix(bg, p.brand, 0.4))
    ink = ink_on(bg)
    y = headline_stack(ad, SIZE / 2, M + 40, SIZE - 2 * M - 80, ink, kind="serif", start=84, floor=52, align="center", lines=2)
    place(ad, (300, max(y + 30, 380), SIZE - 300, top_y + 10), shadow=None, grow=True)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta, 34)[1], p.brand, size=34, align="right")
    logo(ad, "bottom-left")


def giant_word_behind(ad: Ad) -> None:
    p = ad.palette
    bg = [p.light, p.brand, mix(p.brand, WHITE, 0.3)][ad.variant]
    fill(ad, bg)
    word = (ad.slots.big_word or (ad.slots.headline.split(" ")[0] if ad.slots.headline else "NEW")).upper()
    word_color = mix(bg, ink_on(bg), 0.16) if ad.variant != 0 else mix(bg, p.brand, 0.35)
    big = fit(ad.draw, word, "display", SIZE - 2 * M + 40, 520, 120, lines=1)
    write(ad, big, SIZE / 2, 200, word_color, align="center", record=False)
    place(ad, (150, 230, SIZE - 150, 820), tilt=[-14, 12, -8][ad.variant], shadow="drop", align="center")
    ink = ink_on(bg)
    y = 860
    y = text(ad, ad.slots.headline, "sans", M, y, 620, 50, 36, ink, lines=1 if ad.slots.tagline else 2)
    if ad.slots.tagline:
        text(ad, ad.slots.tagline, "sans", M, y + 6, 620, 34, 32, ink, weight="Medium", lines=1)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], p.accent if ad.variant else p.brand, align="right")
    logo(ad, "top-left")


def negative_space(ad: Ad) -> None:
    p = ad.palette
    bg = [WHITE, p.light, (244, 241, 234)][ad.variant]
    fill(ad, bg)
    place(ad, (M + 30, M + 40, 480, 520), align="center", shadow="floor")
    ink = INK
    y = 640
    y = text(ad, ad.slots.headline, "serif", M, y, SIZE - 2 * M - 60, 92, 60, ink, weight="Bold", lines=2)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "serif", M, y + 16, 760, 40, 32, mix(ink, bg, 0.3), weight="Regular", lines=2)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta, 34)[1], None, INK, size=34, outline=INK)
    logo(ad, "bottom-right")


def type_manifesto(ad: Ad) -> None:
    p = ad.palette
    bg, ink = [(WHITE, INK), (INK, WHITE), (p.brand, ink_on(p.brand))][ad.variant]
    fill(ad, bg)
    words = ad.slots.headline or ad.slots.tagline
    y = text(ad, words, "sans", M, M + LOGO_ROW, SIZE - 2 * M, 140, 76, ink, weight="Black", lines=4)
    if ad.slots.tagline and ad.slots.headline:
        text(ad, ad.slots.tagline, "sans", M, y + 24, 560, 40, 32, mix(ink, bg, 0.25), weight="Medium", lines=3)
    place(ad, (620, max(y + 20, 560), SIZE - M, SIZE - M - 10), shadow="floor")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand if ad.variant != 2 else INK)
    logo(ad, "top-left")


def inset_frame(ad: Ad) -> None:
    p = ad.palette
    bg = [p.light, (246, 242, 236), mix(p.brand, WHITE, 0.7)][ad.variant]
    fill(ad, bg)
    d = ad.draw
    d.rectangle((36, 36, SIZE - 36, SIZE - 36), outline=p.dark, width=3)
    ink = INK
    y = tracked(ad, ad.slots.eyebrow, SIZE / 2, 90, 28, p.dark, align="center")
    y = headline_stack(ad, SIZE / 2, max(y, 100), SIZE - 2 * M - 80, ink, kind="serif", start=80, floor=50, align="center", lines=2, weight="Regular")
    bottom = SIZE - 120
    if ad.slots.cta:
        label = f"{ad.slots.cta} →"
        font = face("sans", 36, "SemiBold")
        w = d.textlength(label, font=font)
        d.text((SIZE / 2, bottom + 4), label, font=font, fill=ink, anchor="ma")
        d.line([(SIZE / 2 - w / 2, bottom + 52), (SIZE / 2 + w / 2, bottom + 52)], fill=p.brand, width=4)
        ad.text_boxes.append((round(SIZE / 2 - w / 2), bottom, round(SIZE / 2 + w / 2), bottom + 54))
    place(ad, (220, y + 36, SIZE - 220, bottom - 40), grow=True)
    logo(ad, "top-left")


# ---------------------------------------------------------------- lifestyle / scenes


def scene_still_life(ad: Ad) -> None:
    p = ad.palette
    scene_or(ad, lambda: vgradient(ad, mix(p.light, (240, 232, 220), 0.5), mix(p.soft, (180, 160, 140), 0.4)))
    scrim(ad, (0, 0, SIZE, 400), strength=150, direction="down")
    y = headline_stack(ad, SIZE / 2, M, SIZE - 2 * M, WHITE, kind="serif", start=68, floor=46, align="center", lines=2, weight="Regular")
    place(ad, (220, y + 40, SIZE - 220, SIZE - 140), shadow="floor", grow=True)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta)[1], WHITE, INK, align="center")
    logo(ad, "bottom-right")


def lifestyle_inset(ad: Ad) -> None:
    p = ad.palette
    scene_or(ad, lambda: radial(ad, p.soft, p.dark))
    scrim(ad, (0, 560, SIZE, SIZE), strength=215)
    card = (SIZE - M - 330, M + 20, SIZE - M, M + 350)
    soft_shadow(ad, card)
    ad.draw.rounded_rectangle(card, radius=34, fill=WHITE)
    place(ad, (card[0] + 30, card[1] + 26, card[2] - 30, card[3] - 26), align="center", shadow=None)
    y = SIZE - M - 300
    y = text(ad, ad.slots.headline, "sans", M, y, 760, 76, 48, WHITE, lines=2)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", M, y + 10, 760, 36, 32, (235, 235, 235), weight="Medium", lines=1)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, max(y + 24, SIZE - M - 100), p.brand)
    logo(ad, "top-left")


def split_story(ad: Ad) -> None:
    p = ad.palette
    left_side = ad.variant != 1
    col = [p.brand, p.dark, p.brand][ad.variant]
    fill(ad, p.light)
    cx0, cx1 = (0, 500) if left_side else (580, SIZE)
    ad.draw.rectangle((cx0, 0, cx1, SIZE), fill=col)
    ink = ink_on(col)
    tx = cx0 + M
    y = tracked(ad, ad.slots.eyebrow, tx, M + LOGO_ROW, 26, ink)
    y = text(ad, ad.slots.headline, "serif", tx, max(y, M + LOGO_ROW + 20), 500 - 2 * M, 84, 48, ink, weight="SemiBold", lines=4)
    for b in ad.slots.benefits[:3]:
        y = text(ad, f"— {b}", "sans", tx, y + 14, 500 - 2 * M, 34, 30, ink, weight="Medium", lines=2)
    if ad.slots.tagline and not ad.slots.benefits:
        y = text(ad, ad.slots.tagline, "sans", tx, y + 18, 500 - 2 * M, 34, 30, ink, weight="Medium", lines=3)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, tx, SIZE - M - pill_size(ad.slots.cta, 34)[1], p.accent, size=34)
    px0, px1 = (500, SIZE) if left_side else (0, 580)
    place(ad, (px0 + 30, 150, px1 - 30, SIZE - 120), shadow="floor")
    logo(ad, "top-left" if left_side else "top-right")


def water_ripple(ad: Ad) -> None:
    p = ad.palette
    aqua_top, aqua_bottom = (232, 246, 252), (126, 196, 226)

    def drawn():
        vgradient(ad, aqua_top, aqua_bottom)
        d = ad.draw
        for i in range(7):
            w = 160 + i * 110
            d.ellipse((SIZE / 2 - w, 905 - w * 0.16, SIZE / 2 + w, 905 + w * 0.16), outline=(255, 255, 255), width=3)
        rng = ad.rng
        for _ in range(26):
            x, y, r = rng.uniform(80, 1000), rng.uniform(240, 760), rng.uniform(5, 14)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 200), outline=(170, 215, 236))

    scene_or(ad, drawn)
    ink = mix(p.deep, (10, 40, 70), 0.5)
    y = headline_stack(ad, SIZE / 2, M + LOGO_ROW - 40, SIZE - 2 * M, ink, kind="sans", start=88, floor=52, align="center", lines=2, weight="Light")
    place(ad, (300, max(y + 30, 300), SIZE - 300, 920), shadow=None, reflection=True, grow=True)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta, 34)[1], WHITE, ink, size=34, align="center")
    logo(ad, "top-center")


def flat_lay(ad: Ad) -> None:
    p = ad.palette
    scene_or(ad, lambda: paper(ad, (236, 230, 220)))
    place(ad, (280, 200, SIZE - 280, 760), align="center", shadow="drop", grow=True)
    band = (0, SIZE - 230, SIZE, SIZE)
    layer = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(band, fill=p.brand + (238,))
    ad.canvas.alpha_composite(layer)
    ink = ink_on(p.brand)
    head = fit(ad.draw, ad.slots.headline, "sans", 620, 52, 36, lines=2)
    y = write(ad, head, M, band[1] + (44 if len(head.lines) < 2 or not ad.slots.tagline else 34), ink)
    if ad.slots.tagline and len(head.lines) < 2:
        text(ad, ad.slots.tagline, "sans", M, y + 14, 620, 34, 30, ink, weight="Medium", lines=1)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, band[1] + (230 - pill_size(ad.slots.cta)[1]) / 2, ink, ink_on(ink), align="right")
    logo(ad, "top-center")


def oversized_world(ad: Ad) -> None:
    p = ad.palette
    scene_or(ad, lambda: vgradient(ad, (190, 220, 245), (238, 226, 210)))
    place(ad, (170, 150, SIZE - 170, 860), shadow="floor")
    scrim(ad, (0, 700, SIZE, SIZE), strength=210)
    y = text(ad, ad.slots.headline, "display", M, 830, SIZE - 2 * M, 96, 60, WHITE, lines=1, upper=True)
    if ad.slots.tagline:
        text(ad, ad.slots.tagline, "sans", M, y + 6, 640, 34, 30, (235, 235, 235), weight="Medium", lines=1)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], p.accent, align="right")
    logo(ad, "top-left")


def ingredient_halo(ad: Ad) -> None:
    p = ad.palette
    scene_or(ad, lambda: radial(ad, WHITE, p.soft, center=(0.5, 0.55), radius=0.7))
    ink = ink_on(ad.canvas.getpixel((SIZE // 2, 120))[:3])
    y = headline_stack(ad, SIZE / 2, M, SIZE - 2 * M, ink, kind="sans", start=76, floor=48, align="center", lines=2, weight="ExtraBold")
    cta_top = bottom_cta(ad, p.brand)
    place(ad, (240, y + 40, SIZE - 240, cta_top - 36), shadow="floor", grow=True)
    logo(ad, "bottom-left")


def dark_glow(ad: Ad) -> None:
    p = ad.palette
    radial(ad, mix(p.brand, WHITE, 0.15), (5, 6, 10), center=(0.5, 0.52), radius=0.55)
    y = headline_stack(ad, SIZE / 2, M, SIZE - 2 * M, WHITE, kind="sans", start=80, floor=50, align="center", lines=2, weight="ExtraBold", tagline_color=(205, 205, 210))
    cta_top = bottom_cta(ad, p.brand)
    place(ad, (200, y + 40, SIZE - 200, cta_top - 40), tilt=[0, -10, 8][ad.variant], shadow="drop", align="center", grow=True)
    logo(ad, "bottom-left")


# ---------------------------------------------------------------- proof & benefits


def feature_callouts(ad: Ad) -> None:
    p = ad.palette
    vgradient(ad, WHITE, p.light)
    ink = INK
    y = headline_stack(ad, SIZE / 2, M + 10, SIZE - 2 * M, ink, kind="sans", start=72, floor=46, align="center", lines=2)
    d = ad.draw
    benefits = ad.slots.benefits[:4]
    if is_wide(ad):
        box = place(ad, (M + 40, y + 50, SIZE - M - 40, SIZE - 330), shadow="floor")
        cols = max(1, len(benefits))
        cw = (SIZE - 2 * M) // cols
        for i, b in enumerate(benefits):
            block = fit(d, b, "sans", cw - 60, 34, 28, weight="SemiBold", lines=2)
            bw, bh = block.width(d) + 40, block.height + 26
            bx, by = M + i * cw + (cw - bw) / 2, SIZE - 300
            anchor = (box[0] + (box[2] - box[0]) * (i + 0.5) / cols, box[3] - (box[3] - box[1]) * 0.25)
            d.line([(bx + bw / 2, by), anchor], fill=p.brand, width=3)
            d.ellipse((anchor[0] - 9, anchor[1] - 9, anchor[0] + 9, anchor[1] + 9), fill=p.brand, outline=WHITE, width=3)
            d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=bh / 2, fill=WHITE, outline=p.brand, width=3)
            write(ad, block, bx + 20, by + 13, ink)
        if ad.slots.cta:
            pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta, 34)[1], p.brand, size=34, align="center")
        logo(ad, "bottom-left")
        return
    box = place(ad, (370, y + 40, SIZE - 370, SIZE - 150), shadow="floor")
    slots = [("left", 0.25), ("right", 0.4), ("left", 0.7), ("right", 0.8)]
    for b, (side, t) in zip(benefits, slots):
        anchor = (box[0] + (box[2] - box[0]) * (0.2 if side == "left" else 0.8), box[1] + (box[3] - box[1]) * t)
        block = fit(d, b, "sans", 300, 34, 30, weight="SemiBold", lines=2)
        bw, bh = block.width(d) + 40, block.height + 26
        bx = M if side == "left" else SIZE - M - bw
        by = anchor[1] - bh / 2
        edge = (bx + bw, anchor[1]) if side == "left" else (bx, anchor[1])
        d.line([edge, anchor], fill=p.brand, width=3)
        d.ellipse((anchor[0] - 9, anchor[1] - 9, anchor[0] + 9, anchor[1] + 9), fill=p.brand, outline=WHITE, width=3)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=bh / 2, fill=WHITE, outline=p.brand, width=3)
        write(ad, block, bx + 20, by + 13, ink)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta, 34)[1], p.brand, size=34, align="center")
    logo(ad, "bottom-left")


def benefit_checklist(ad: Ad) -> None:
    p = ad.palette
    vgradient(ad, (250, 252, 255), mix(p.light, (220, 236, 248), 0.5))
    ink = INK
    col = 560
    y = text(ad, ad.slots.headline, "sans", M, M + LOGO_ROW, col - M, 76, 44, ink, weight="ExtraBold", lines=4)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", M, y + 12, col - M, 34, 30, mix(ink, WHITE, 0.3), weight="Medium", lines=2)
    y += 30
    for b in ad.slots.benefits[:3]:
        check_icon(ad, M, y, 46, p.brand)
        y = text(ad, b, "sans", M + 66, y + 4, col - M - 66, 36, 30, ink, weight="SemiBold", lines=2) + 22
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand)
    place(ad, side_box(ad, col, y), shadow="floor")
    logo(ad, "top-left")


def numbered_steps(ad: Ad) -> None:
    p = ad.palette
    fill(ad, p.light)
    ad.draw.ellipse((480, 120, 1300, 940), fill=mix(p.light, p.brand, 0.18))
    ink = INK
    y = text(ad, ad.slots.headline, "sans", M, M + LOGO_ROW, 560, 70, 44, ink, weight="ExtraBold", lines=3, upper=True)
    y += 34
    steps = ad.slots.steps or ad.slots.benefits
    for i, step in enumerate(steps[:3], 1):
        size = 52
        ad.draw.ellipse((M, y, M + size, y + size), fill=p.brand)
        ad.draw.text((M + size / 2, y + size / 2), str(i), font=face("sans", 30, "Bold"), fill=ink_on(p.brand), anchor="mm")
        y = text(ad, step, "sans", M + 74, y + 8, 470, 34, 30, ink, weight="Medium", lines=2) + 26
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand)
    place(ad, side_box(ad, 580, y), shadow="floor")
    logo(ad, "top-left")


def big_number(ad: Ad) -> None:
    p = ad.palette
    bg = [p.light, WHITE, p.brand][ad.variant]
    fill(ad, bg)
    ink = ink_on(bg)
    stat = ad.slots.stat or ad.slots.badge or "NEW"
    block = fit(ad.draw, stat, "display", 560, 300, 150, lines=1)
    y = write(ad, block, M, M + LOGO_ROW - 20, p.brand if ad.variant != 2 else ink)
    y = text(ad, ad.slots.headline, "sans", M, y + 10, 540, 52, 36, ink, weight="Bold", lines=3)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", M, y + 12, 540, 32, 30, mix(ink, bg, 0.3), weight="Medium", lines=2)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], INK if ad.variant == 2 else p.brand)
    place(ad, side_box(ad, 600, y), shadow="floor")
    logo(ad, "top-left")


def tagline_quote(ad: Ad) -> None:
    p = ad.palette
    vgradient(ad, p.soft, p.brand)
    quote = ad.slots.tagline or ad.slots.headline
    card = (M, M + LOGO_ROW, SIZE - M - 40, 520)
    d = ad.draw
    block = fit(d, quote, "italic", card[2] - card[0] - 120, 64, 40, lines=4)
    card = (card[0], card[1], card[2], card[1] + block.height + 170)
    soft_shadow(ad, card)
    ad.draw.rounded_rectangle(card, radius=36, fill=WHITE)
    ad.draw.text((card[0] + 50, card[1] + 10), "“", font=face("serif", 160, "Black"), fill=p.brand, anchor="la")
    write(ad, block, card[0] + 60, card[1] + 110, INK)
    if ad.slots.tagline and ad.slots.headline:
        text(ad, ad.slots.headline, "sans", M, card[3] + 30, 520, 44, 32, ink_on(p.brand), lines=3)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], WHITE, INK)
    place(ad, (420 if is_wide(ad) else 560, max(card[3] + 20, 480), SIZE - M, SIZE - M - (110 if is_wide(ad) else 10)), shadow="drop")
    logo(ad, "top-left")


def us_vs_them(ad: Ad) -> None:
    p = ad.palette
    fill(ad, (236, 236, 238))
    ad.draw.rectangle((0, 0, SIZE // 2, SIZE), fill=p.brand)
    ink_l, ink_r = ink_on(p.brand), INK
    band_h = M + 20 + fit(ad.draw, ad.slots.headline, "sans", SIZE - 2 * M, 56, 38, lines=2).height + 34 if ad.slots.headline else 0
    if band_h:
        ad.draw.rectangle((0, 0, SIZE, band_h), fill=INK)
        text(ad, ad.slots.headline, "sans", SIZE / 2, M + 10, SIZE - 2 * M, 56, 38, WHITE, lines=2, align="center")
    place(ad, (M + 20, band_h + 40, SIZE // 2 - M - 20, 560), shadow="floor")
    d = ad.draw
    d.rounded_rectangle((SIZE // 2 + M + 60, 260, SIZE - M - 60, 500), radius=40, fill=(205, 205, 210))
    tracked(ad, "the usual way", SIZE * 0.75, 365, 28, (110, 110, 118), align="center")
    d.ellipse((SIZE / 2 - 48, 330, SIZE / 2 + 48, 426), fill=INK)
    d.text((SIZE / 2, 378), "VS", font=face("display", 44), fill=WHITE, anchor="mm")
    y = 620
    for b in ad.slots.benefits[:3]:
        check_icon(ad, M, y, 42, WHITE)
        text(ad, b, "sans", M + 60, y + 4, SIZE // 2 - M - 80, 32, 28, ink_l, weight="SemiBold", lines=2)
        check_icon(ad, SIZE // 2 + M, y, 42, (170, 170, 176), ok=False)
        before = len(ad.text_boxes)
        text(ad, b, "sans", SIZE // 2 + M + 60, y + 4, SIZE // 2 - M - 80, 32, 28, mix(ink_r, WHITE, 0.45), weight="Medium", lines=2)
        for bx0, by0, bx1, by1 in ad.text_boxes[before:]:
            mid = (by0 + by1) / 2 - 3
            ad.draw.line([(bx0, mid), (bx1, mid)], fill=mix(ink_r, WHITE, 0.45), width=3)
        y += 96
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], INK, align="right")
    logo(ad, "bottom-left")


def phone_mockup(ad: Ad) -> None:
    p = ad.palette
    vgradient(ad, p.light, p.soft)
    blob(ad, (820, 300), 260, mix(p.soft, p.brand, 0.3))
    ink = INK
    y = text(ad, ad.slots.headline, "sans", M, M + LOGO_ROW, 520, 74, 44, ink, weight="ExtraBold", lines=4)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", M, y + 10, 500, 34, 30, mix(ink, WHITE, 0.3), weight="Medium", lines=2)
    y += 26
    for b in ad.slots.benefits[:3]:
        check_icon(ad, M, y, 40, p.brand)
        y = text(ad, b, "sans", M + 56, y + 2, 450, 32, 28, ink, weight="SemiBold", lines=2) + 18
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand)
    phone = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
    pd = ImageDraw.Draw(phone)
    pd.rounded_rectangle((0, 0, 399, 799), radius=62, fill=(22, 22, 26))
    pd.rounded_rectangle((16, 16, 383, 783), radius=50, fill=WHITE)
    pd.rounded_rectangle((150, 30, 250, 54), radius=12, fill=(22, 22, 26))
    inner = Ad(phone, ad.product, ad.slots, ad.palette)
    place(inner, (46, 120, 354, 640), align="center", shadow="floor")
    phone = phone.rotate(-6, resample=Image.BICUBIC, expand=True)
    soft_shadow(ad, (620, 160, 620 + phone.width - 40, 160 + phone.height - 40), radius=60, opacity=80)
    ad.canvas.alpha_composite(phone, (600, 150))
    pb = inner.product_box
    ad.product_box = (600 + pb[0], 150 + pb[1], 600 + pb[2], 150 + pb[3])
    logo(ad, "top-left")


# ---------------------------------------------------------------- playful pop


def script_flank(ad: Ad) -> None:
    p = ad.palette
    rings(ad, [mix(p.brand, WHITE, 0.15), p.brand], step=95)
    words = (ad.slots.big_word or ad.slots.headline or "Fresh").split()
    left, right = (words[0], words[1]) if len(words) >= 2 else (words[0], "")
    rotated_text(ad, left, "script", (215, 560), 150, 90, WHITE)
    rotated_text(ad, right, "script", (SIZE - 215, 560), 150, -90, WHITE)
    tag = ad.slots.tagline or (ad.slots.headline if ad.slots.big_word else "")
    y = text(ad, tag, "sans", SIZE / 2, M + 10, 640, 46, 34, WHITE, weight="Bold", lines=2, align="center")
    place(ad, (300, max(y + 20, 170), SIZE - 300, SIZE - 160), tilt=[-18, 15, -10][ad.variant], shadow="drop", align="center")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta)[1], p.accent, align="center")
    logo(ad, "bottom-left")


def doodle_pop(ad: Ad) -> None:
    p = ad.palette
    fill(ad, (252, 250, 244))
    d = ad.draw
    for i in range(5):  # wavy brand-tint stripes
        y = 120 + i * 210
        pts = [(x, y + 26 * math.sin(x / 120 + i)) for x in range(-20, SIZE + 40, 20)]
        d.line(pts, fill=mix(p.brand, WHITE, 0.82), width=46)
    ink = p.brand if _luminance(p.brand) < 0.5 else INK
    y = text(ad, ad.slots.headline, "sans", M, M + LOGO_ROW, 470, 104, 56, ink, weight="Black", lines=4)
    if ad.slots.tagline:
        tag = fit(d, ad.slots.tagline, "hand", 420, 64, 42, lines=2)
        bw, bh = tag.width(d) + 40, tag.height + 20
        d.rounded_rectangle((M - 6, y + 20, M - 6 + bw, y + 20 + bh), radius=20, fill=p.accent)
        write(ad, tag, M + 14, y + 26, ink_on(p.accent))
        y += bh + 40
    box = place(ad, (560, 180, SIZE - M + 10, SIZE - 150), tilt=[8, -6, 4][ad.variant], shadow="drop", align="center")
    dashed_curve(ad, [(box[0] - 30, box[3] - 40), (box[0] - 160, box[3] + 80), (M + 100, SIZE - 120)], p.brand)
    sparkle(ad, (box[0] - 30, box[1] + 30), 46, p.brand)
    sparkle(ad, (box[2] - 10, box[3] + 10), 40, p.brand)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand, align="right")
    logo(ad, "top-left")


def blob_sticker(ad: Ad) -> None:
    p = ad.palette
    bg = [p.light, mix(p.accent, WHITE, 0.75), p.soft][ad.variant]
    fill(ad, bg)
    blob(ad, (560, 600), 340, mix(bg, p.brand, 0.45))
    blob(ad, (880, 230), 140, mix(bg, p.brand, 0.25))
    halftone(ad, mix(bg, INK, 0.25), (M, 700, 330, SIZE - 120), spacing=26, max_r=5, fade_down=False)
    ink = INK
    y = M + LOGO_ROW - 20
    block = fit(ad.draw, ad.slots.headline, "sans", SIZE - 2 * M, 92, 52, weight="Black", lines=2)
    write(ad, block, M + 6, y + 6, p.brand, record=False)
    y = write(ad, block, M, y, ink)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "hand", M, y + 6, 700, 56, 40, ink, lines=1)
    place(ad, (300, y + 30, SIZE - 220, SIZE - 140), tilt=-6, outline=14, shadow="drop", align="center")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], INK, align="right")
    logo(ad, "top-left")


def paper_collage(ad: Ad) -> None:
    p = ad.palette
    paper(ad, (214, 190, 156))
    d = ad.draw
    sheet = (110, 200, SIZE - 110, SIZE - 170)
    d.polygon([(sheet[0], sheet[1] + 10), (sheet[2], sheet[1]), (sheet[2] - 8, sheet[3]), (sheet[0] + 6, sheet[3] - 6)], fill=(250, 247, 240))
    place(ad, (sheet[0] + 90, sheet[1] + 60, sheet[2] - 90, sheet[3] - 40), tilt=4, outline=10, shadow="drop", align="center")
    for (cx, cy, ang) in [(sheet[0] + 30, sheet[1] + 10, 35), (sheet[2] - 30, sheet[1] + 6, -30)]:
        tape = Image.new("RGBA", (170, 48), mix(p.brand, WHITE, 0.55) + (190,))
        tape = tape.rotate(ang, expand=True, resample=Image.BICUBIC)
        ad.canvas.alpha_composite(tape, (round(cx - tape.width / 2), round(cy - tape.height / 2)))
    ink = INK
    text(ad, ad.slots.headline, "hand", M, M, SIZE - 2 * M - 230, 96, 56, ink, lines=1)
    tag = ad.slots.tagline
    if tag:
        f = fit(d, tag, "hand", 560, 48, 36, lines=1)
        tw = f.width(d) + 44
        label = (SIZE - M - tw, SIZE - M - 76, SIZE - M, SIZE - M)
        d.rectangle(label, fill=p.accent)
        write(ad, f, label[0] + 22, label[1] + 14, ink_on(p.accent))
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta, 34)[1], INK, size=34)
    logo(ad, "top-right")


def speech_bubble(ad: Ad) -> None:
    p = ad.palette
    bg = [p.brand, p.dark, mix(p.brand, WHITE, 0.2)][ad.variant]
    fill(ad, bg)
    d = ad.draw
    words = ad.slots.headline or ad.slots.tagline
    block = fit(d, words, "sans", 580, 64, 40, weight="ExtraBold", lines=4)
    bub = (M, M + LOGO_ROW - 30, M + block.width(d) + 90, M + LOGO_ROW - 30 + block.height + 70)
    d.rounded_rectangle(bub, radius=44, fill=WHITE)
    d.polygon([(bub[2] - 140, bub[3] - 4), (bub[2] - 60, bub[3] - 4), (bub[2] + 10, bub[3] + 80)], fill=WHITE)
    write(ad, block, bub[0] + 45, bub[1] + 35, INK)
    y = bub[3] + 40
    if ad.slots.tagline and ad.slots.headline:
        text(ad, ad.slots.tagline, "sans", M, y + 60, 380, 36, 30, ink_on(bg), weight="SemiBold", lines=3)
    place(ad, (430, bub[3] + 40, SIZE - M, SIZE - M - 10), shadow="drop", tilt=[6, -4, 0][ad.variant])
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], WHITE, INK)
    logo(ad, "top-right")


def comic_scene(ad: Ad) -> None:
    p = ad.palette
    if not scene_or(ad, lambda: rays(ad, mix(p.brand, WHITE, 0.55), mix(p.brand, WHITE, 0.35))):
        halftone(ad, mix(p.brand, WHITE, 0.15), (0, 0, SIZE, 420), spacing=30, max_r=8)
    d = ad.draw
    words = ad.slots.headline or ad.slots.tagline
    block = fit(d, words, "hand", 640, 76, 48, lines=3)
    bub = (M, M, M + block.width(d) + 80, M + block.height + 56)
    d.rounded_rectangle(bub, radius=30, fill=WHITE, outline=INK, width=5)
    d.polygon([(bub[0] + 120, bub[3] - 3), (bub[0] + 190, bub[3] - 3), (bub[0] + 250, bub[3] + 70)], fill=WHITE, outline=INK)
    d.line([(bub[0] + 123, bub[3] - 2), (bub[0] + 187, bub[3] - 2)], fill=WHITE, width=6)
    write(ad, block, bub[0] + 40, bub[1] + 26, INK)
    place(ad, (540, 360, SIZE - M, SIZE - M - 30), shadow="drop", outline=8)
    if ad.slots.tagline and ad.slots.headline:
        text(ad, ad.slots.tagline, "hand", M, SIZE - M - 180, 440, 54, 40, INK, lines=2)
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], INK)
    logo(ad, "top-right")


# ---------------------------------------------------------------- bold promo


def starburst_badge(ad: Ad) -> None:
    p = ad.palette
    bg = [p.brand, (230, 40, 45), INK][ad.variant] if ad.variant else p.brand
    fill(ad, bg)
    halftone(ad, mix(bg, WHITE, 0.18), (0, 0, SIZE, 560), spacing=30, max_r=8)
    ink = ink_on(bg)
    y = text(ad, ad.slots.headline, "display", M, M + LOGO_ROW, 470, 160, 84, ink, lines=4, upper=True)
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", M, y + 16, 440, 36, 30, ink, weight="SemiBold", lines=2)
    box = place(ad, (520, 330, SIZE - 150, SIZE - M - 20), shadow="drop", tilt=-6)
    # The badge sits at the product's top corner, not on its face.
    starburst(ad, (min(box[2] + 30, SIZE - M - 100), max(box[1] - 30, M + 110)), 115, p.accent, ad.slots.badge or "NEW")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], WHITE if bg != WHITE else INK, size=38)
    logo(ad, "top-left")


def diagonal_flash(ad: Ad) -> None:
    p = ad.palette
    a, b = [(p.brand, INK), (INK, p.brand), (p.accent, p.brand)][ad.variant]
    fill(ad, a)
    d = ad.draw
    d.polygon([(0, SIZE * 0.9), (SIZE, SIZE * 0.38), (SIZE, SIZE), (0, SIZE)], fill=b)
    for i in range(6):  # speed lines
        y = 300 + i * 46
        d.line([(SIZE - 360 + i * 20, y), (SIZE - 60, y - 120)], fill=mix(a, WHITE, 0.35), width=6)
    ink = ink_on(a)
    y = text(ad, ad.slots.headline, "display", M, M + LOGO_ROW, 470, 130, 72, ink, lines=3, upper=True)
    if ad.slots.tagline:
        text(ad, ad.slots.tagline, "sans", M, y + 16, 440, 34, 30, ink, weight="SemiBold", lines=2)
    place(ad, (520, 260, SIZE - M, SIZE - 150), tilt=-8, shadow="drop", align="center")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE - M, SIZE - M - pill_size(ad.slots.cta)[1], WHITE if b != WHITE else INK, align="right")
    if ad.slots.badge:
        tracked(ad, ad.slots.badge, M, SIZE - M - 40, 34, ink_on(b), spacing=0.12, weight="Black")
    logo(ad, "top-left")


def type_sandwich(ad: Ad) -> None:
    p = ad.palette
    bg = [(236, 236, 240), p.light, p.brand][ad.variant]
    fill(ad, bg)
    ink = INK if ad.variant != 2 else ink_on(bg)
    words = (ad.slots.big_word or ad.slots.headline or "New").upper().split()
    first, rest = words[0], " ".join(words[1:3])
    top = fit(ad.draw, first, "display", SIZE - 2 * M, 300, 120, lines=1)
    y = write(ad, top, SIZE / 2, M + LOGO_ROW + 10, ink, align="center", record=False)
    back = fit(ad.draw, rest, "display", SIZE - 2 * M, 300, 120, lines=1) if rest else None
    if back:
        write(ad, back, SIZE / 2, y - 10, ink, align="center", record=False)
    place(ad, (190, round(y - top.height * 0.35), SIZE - 190, 800), tilt=[-6, 0, 6][ad.variant], shadow="drop", align="center", grow=True)
    if back:  # the same word again in outline, in front of the product
        write(ad, back, SIZE / 2, y - 10, None, align="center", stroke=(3, ink), record=False)
    yy = 830
    tag = ad.slots.tagline or (ad.slots.headline if ad.slots.big_word else "")
    yy = text(ad, tag, "sans", SIZE / 2, yy, SIZE - 2 * M - 100, 36, 30, ink, weight="Medium", lines=2, align="center")
    if ad.slots.cta:
        pill(ad, ad.slots.cta, SIZE / 2, SIZE - M - pill_size(ad.slots.cta)[1], p.accent, INK, align="center")
    logo(ad, "top-center")


def rings_orbit(ad: Ad) -> None:
    p = ad.palette
    base = [p.deep, p.brand, p.light][ad.variant]
    fill(ad, base)
    d = ad.draw
    cx, cy = SIZE / 2, 590
    for i, r in enumerate([420, 330, 240]):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=mix(base, ink_on(base), 0.2 + 0.08 * i), width=3)
    rng = ad.rng
    for r in (420, 330, 240):
        a = rng.uniform(0, 2 * math.pi)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        d.ellipse((x - 12, y - 12, x + 12, y + 12), fill=p.accent)
    ink = ink_on(base)
    y = headline_stack(ad, SIZE / 2, M, SIZE - 2 * M, ink, kind="sans", start=80, floor=48, align="center", lines=2, weight="ExtraBold")
    cta_top = bottom_cta(ad, p.accent)
    place(ad, (330, max(y + 30, 300), SIZE - 330, min(cta_top - 30, 860)), align="center", shadow="drop", grow=True)
    logo(ad, "bottom-left")


def corner_ribbon(ad: Ad) -> None:
    p = ad.palette
    vgradient(ad, WHITE, p.light)
    d = ad.draw
    d.ellipse((260, 260, 1020, 1020), fill=mix(p.light, p.brand, 0.14))
    ink = INK
    y = headline_stack(ad, M, M + LOGO_ROW, 620, ink, kind="sans", start=76, floor=46, lines=3, weight="ExtraBold", tagline_color=mix(ink, WHITE, 0.3))
    place(ad, (300, max(y + 30, 380), SIZE - 160, SIZE - M - 20), shadow="floor")
    band = Image.new("RGBA", (620, 84), p.brand + (255,))
    bd = ImageDraw.Draw(band)
    bd.text((310, 42), (ad.slots.badge or "NEW").upper(), font=face("sans", 36, "ExtraBold"), fill=ink_on(p.brand), anchor="mm")
    band = band.rotate(-45, expand=True, resample=Image.BICUBIC)
    ad.canvas.alpha_composite(band, (SIZE - band.width // 2 - 150, -band.height // 2 + 150))
    if ad.slots.cta:
        pill(ad, ad.slots.cta, M, SIZE - M - pill_size(ad.slots.cta)[1], p.brand)
    logo(ad, "top-left")


def event_title(ad: Ad) -> None:
    p = ad.palette
    radial(ad, mix(p.brand, (20, 10, 40), 0.4), (8, 6, 14), center=(0.5, 0.35), radius=0.7)
    glow_layer = Image.new("RGBA", ad.canvas.size, (0, 0, 0, 0))
    block = fit(ad.draw, ad.slots.headline or ad.slots.big_word, "display", SIZE - 2 * M, 130, 72, lines=2, upper=True)
    block.draw_lines(ImageDraw.Draw(glow_layer), SIZE / 2, M + 30, p.brand + (255,), align="center")
    ad.canvas.alpha_composite(glow_layer.filter(ImageFilter.GaussianBlur(16)))
    y = write(ad, block, SIZE / 2, M + 30, WHITE, align="center")
    if ad.slots.eyebrow:
        strip = (0, y + 20, SIZE, y + 96)
        ad.draw.rectangle(strip, fill=p.brand)
        tracked(ad, ad.slots.eyebrow, SIZE / 2, strip[1] + 20, 34, ink_on(p.brand), align="center", weight="Bold")
        y = strip[3]
    if ad.slots.tagline:
        y = text(ad, ad.slots.tagline, "sans", SIZE / 2, y + 20, SIZE - 2 * M, 36, 30, (220, 220, 230), weight="Medium", lines=2, align="center")
    cta_top = bottom_cta(ad, p.accent)
    place(ad, (260, y + 30, SIZE - 260, cta_top - 30), shadow="drop", align="center", grow=True)
    logo(ad, "bottom-left")


# ---------------------------------------------------------------- registry


@dataclass(frozen=True)
class Template:
    id: str
    family: str  # the bandit image style it belongs to
    suits: str  # one line for the creative LLM
    render: Callable[[Ad], None]
    scene: str = ""  # non-empty: the image model paints this background (a hint for the prompt)
    needs: tuple[str, ...] = ()  # slots that must be filled for the template to be chosen
    humans: bool = False


T = Template
TEMPLATES: dict[str, Template] = {t.id: t for t in [
    # minimalist
    T("centered_hero", "minimalist", "any packaged product; clean hero on a soft gradient", centered_hero),
    T("icon_on_void", "minimalist", "premium/luxury: fragrance, watches, jewellery, spirits-free drinks; spotlight on black", icon_on_void),
    T("podium_showcase", "minimalist", "beauty, skincare, gadgets, bottles; product on a pastel podium", podium_showcase),
    T("giant_word_behind", "minimalist", "sneakers, fashion, drinks, bold launches; one huge word behind the tilted product", giant_word_behind),
    T("negative_space", "minimalist", "confident, premium or understated brands; tiny product, big calm space, serif line", negative_space),
    T("type_manifesto", "minimalist", "ingredient-honest or no-nonsense brands; the statement is the visual", type_manifesto),
    T("inset_frame", "minimalist", "artisan, boutique, home goods; framed editorial layout", inset_frame),
    # lifestyle_aspirational
    T("scene_still_life", "lifestyle_aspirational", "premium beauty, home, food & drink; product on a natural material surface",
      scene_still_life, scene="a natural material surface (stone, sand, wood or linen) in soft daylight with gentle shadows, empty in the middle"),
    T("lifestyle_inset", "lifestyle_aspirational", "apparel, fitness, food, travel; a lifestyle scene with the product shown on a card",
      lifestyle_inset, scene="a candid real-life scene where the product would be used, with the right side of the frame calm", humans=True),
    T("split_story", "lifestyle_aspirational", "fashion, furniture, premium products; colour column with the story, product beside it", split_story),
    T("water_ripple", "lifestyle_aspirational", "drinks, water, skincare, fresh fragrance; aqua, ripples and droplets",
      water_ripple, scene="clear shallow water with soft ripples, a splash and droplets, pale aqua light, empty centre"),
    T("flat_lay", "lifestyle_aspirational", "accessories, stationery, watches, snacks; top-down flat lay on a textured surface",
      flat_lay, scene="a top-down flat lay surface (marble, linen or wood) with a few small props around the edges, empty centre"),
    T("oversized_world", "lifestyle_aspirational", "launches and statement products; product shown giant in a real street or landscape",
      oversized_world, scene="a wide city street or open landscape at eye level with tiny people far away, empty middle ground"),
    T("ingredient_halo", "lifestyle_aspirational", "natural foods, juices, skincare with hero ingredients; ingredients floating around the product",
      ingredient_halo, scene="the product's key ingredients floating and scattered around an empty centre, pastel studio background"),
    T("dark_glow", "lifestyle_aspirational", "tech, energy drinks, cola, gaming; dark backdrop with a glow in the brand colour", dark_glow),
    # testimonial_social_proof (proof & benefits)
    T("feature_callouts", "testimonial_social_proof", "gadgets, skincare, supplements with clear features; labels pointing at the product", feature_callouts, needs=("benefits",)),
    T("benefit_checklist", "testimonial_social_proof", "health, personal care, cleaning, services; claim plus ticked benefits", benefit_checklist, needs=("benefits",)),
    T("numbered_steps", "testimonial_social_proof", "routines, kits, apps, recipes; how it works in 3 steps", numbered_steps, needs=("steps",)),
    T("big_number", "testimonial_social_proof", "a real number from the idea (price, % natural, minutes); the number is the hero", big_number, needs=("stat",)),
    T("tagline_quote", "testimonial_social_proof", "brands with a strong tagline; the tagline set as a quote card", tagline_quote),
    T("us_vs_them", "testimonial_social_proof", "products that replace a worse habit; ours vs the usual way", us_vs_them, needs=("benefits",)),
    T("phone_mockup", "testimonial_social_proof", "apps, online stores, digital services; product on a phone screen with benefits", phone_mockup),
    # humor_meme (playful pop)
    T("script_flank", "humor_meme", "juices, sweets, desserts, fun drinks; script words either side on bright rings", script_flank),
    T("doodle_pop", "humor_meme", "snacks, youth brands, FMCG; giant bold headline with hand-drawn doodles", doodle_pop),
    T("blob_sticker", "humor_meme", "D2C, kids, snacks, playful brands; product as a sticker on colour blobs", blob_sticker),
    T("paper_collage", "humor_meme", "handmade, craft, stationery, cafés; kraft paper collage with tape", paper_collage),
    T("speech_bubble", "humor_meme", "apps, delivery, challenger brands; the product 'talks' on a signature colour", speech_bubble),
    T("comic_scene", "humor_meme", "energy drinks, snacks, humour-led brands; flat cartoon scene with the real product",
      comic_scene, scene="a flat 2D cartoon illustration scene with bold outlines and bright colours, empty right half", humans=True),
    # urgency_scarcity (bold promo)
    T("starburst_badge", "urgency_scarcity", "offers, launches, new flavours; starburst badge on bold colour", starburst_badge),
    T("diagonal_flash", "urgency_scarcity", "flash offers and drops; diagonal split with speed lines", diagonal_flash),
    T("type_sandwich", "urgency_scarcity", "new product launches; huge stacked words with the product between them", type_sandwich),
    T("rings_orbit", "urgency_scarcity", "tech and product launches; orbit rings around the product", rings_orbit),
    T("corner_ribbon", "urgency_scarcity", "new or improved products, pharmacy, beauty; corner ribbon badge", corner_ribbon),
    T("event_title", "urgency_scarcity", "events, launches, workshops, pop-ups; big glowing title with a date strip", event_title),
]}

FAMILIES: dict[str, list[str]] = {}
for _t in TEMPLATES.values():
    FAMILIES.setdefault(_t.family, []).append(_t.id)


def family_menu(family: str, only: str | None = None) -> str:
    """The family's templates as prompt lines for the creative LLM (just
    `only` when the user picked a template)."""
    ids = [only] if only in TEMPLATES else (FAMILIES.get(family) or FAMILIES["minimalist"])
    lines = []
    for tid in ids:
        t = TEMPLATES[tid]
        need = f" (only if you fill: {', '.join(t.needs)})" if t.needs else ""
        lines.append(f"- {t.id}: {t.suits}{need}")
    return "\n".join(lines)


def resolve(template_id: str | None, family: str, slots: Slots) -> Template:
    """The template to draw: the requested one if it's in the family and its
    required slots are filled, else the family's first."""
    ids = FAMILIES.get(family) or FAMILIES["minimalist"]
    t = TEMPLATES.get(template_id or "")
    if t and t.id in ids and all(getattr(slots, n) for n in t.needs):
        return t
    return TEMPLATES[ids[0]]


def render(
    product_png: bytes, template: str, slots: Slots, *, brand_color: str | None = None, logo_bytes: bytes | None = None,
    scene_bytes: bytes | None = None, seed: int = 0,
) -> Ad:
    product = Image.open(io.BytesIO(product_png)).convert("RGBA")
    # Trim to the solid subject: a feathered edge leaves faint pixels that
    # would otherwise count as part of the product and shrink it in the layout.
    bbox = product.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:
        product = product.crop(bbox)
    scene = None
    if scene_bytes:
        try:
            scene = Image.open(io.BytesIO(scene_bytes)).convert("RGB")
        except Exception:
            logger.warning("scene image unreadable, drawing the background instead")
    t = TEMPLATES.get(template) or TEMPLATES["centered_hero"]
    ad = Ad(Image.new("RGBA", (SIZE, SIZE), WHITE + (255,)), product, slots, Palette(_rgb(brand_color)), scene, _open_logo(logo_bytes), seed)
    t.render(ad)
    return ad


def compose_product_ad(
    product_png: bytes, template: str, slots: Slots | dict, *, brand_color: str | None = None,
    logo_bytes: bytes | None = None, scene_bytes: bytes | None = None, seed: int = 0,
) -> bytes:
    """The finished ad as JPEG bytes."""
    if isinstance(slots, dict):
        slots = Slots.from_dict(slots)
    return _jpeg(render(product_png, template, slots, brand_color=brand_color, logo_bytes=logo_bytes, scene_bytes=scene_bytes, seed=seed).canvas)
