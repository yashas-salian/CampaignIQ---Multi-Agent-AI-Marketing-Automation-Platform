"""Render a ~17 s looping product-flow simulation of CampaignIQ as an animated WebP.

Scenes: idea typed -> feasibility scored -> personas -> Gate 2 approved ->
published -> reward climbs. Drawn at 2x and downsampled for smooth edges.
Usage (from the repo root): .venv/Scripts/python.exe frontend/scripts/render_demo.py frontend/public/media/demo-loop.webp
Windows-only as written: it loads Segoe UI / Consolas from C:/Windows/Fonts.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
S = 2  # supersample factor
FPS = 20
DURATION = 17.0
# Each scene's motion finishes in the first ACTION_SHARE of its time, then the
# finished screen holds so viewers can read it.
ACTION_SHARE = 0.65
FRAMES = int(FPS * DURATION)

BG = (12, 14, 16)
RAISED = (18, 21, 26)
SURFACE = (22, 26, 32)
BORDER = (36, 42, 51)
TEXT = (237, 241, 245)
MUTED = (141, 151, 165)
ACCENT = (255, 107, 61)
INK = (17, 19, 22)
SUCCESS = (62, 207, 142)

FONT_DIR = "C:/Windows/Fonts/"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_DIR + name, size * S)


F = {
    "h1": font("seguisb.ttf", 30),
    "h2": font("seguisb.ttf", 22),
    "body": font("segoeui.ttf", 18),
    "small": font("segoeui.ttf", 15),
    "tiny": font("segoeui.ttf", 13),
    "mono": font("consola.ttf", 14),
    "big": font("segoeuib.ttf", 56),
    "num": font("seguisb.ttf", 26),
}

LOGO_PX = 28  # logical size of the brand tile in the window chrome
LOGO = (
    Image.open(Path(__file__).resolve().parents[1] / "public" / "brand" / "logo-256.webp")
    .convert("RGB")
    .resize((LOGO_PX * S, LOGO_PX * S), Image.LANCZOS)
)
LOGO_MASK = Image.new("L", LOGO.size, 0)
ImageDraw.Draw(LOGO_MASK).rounded_rectangle((0, 0, LOGO.width - 1, LOGO.height - 1), radius=int(LOGO.width * 0.22), fill=255)

SCENES = [  # (start, end, step index)
    (0.0, 3.0, 0),   # idea typed
    (3.0, 5.8, 1),   # feasibility scored
    (5.8, 8.6, 2),   # personas
    (8.6, 11.6, 3),  # Gate 2 approved
    (11.6, 14.0, 4),  # published
    (14.0, DURATION, 5),  # reward climbs
]
STEPS = ["Idea", "Feasibility", "Personas", "Gate 2", "Publish", "Learn"]
IDEA = "Meal-prep subscription for night-shift nurses"


def ease(x: float) -> float:
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def P(*v):
    """Scale logical coordinates to the supersampled canvas."""
    return [int(x * S) for x in v]


class Canvas:
    def __init__(self):
        self.img = Image.new("RGB", (W * S, H * S), BG)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x, y, w, h, fill, r=14, outline=None, width=1):
        self.d.rounded_rectangle(P(x, y, x + w, y + h), radius=r * S, fill=fill, outline=outline, width=width * S)

    def text(self, x, y, s, f, fill=TEXT, anchor="la"):
        self.d.text(P(x, y), s, font=F[f], fill=fill, anchor=anchor)

    def tw(self, s, f):
        return self.d.textlength(s, font=F[f]) / S


def scene_progress(t):
    for start, end, idx in SCENES:
        if start <= t < end:
            return idx, (t - start) / (end - start), t - start
    return SCENES[-1][2], 1.0, DURATION - SCENES[-1][0]


def draw_chrome(c: Canvas):
    c.rect(0, 0, W, 52, RAISED, r=0)
    c.d.line(P(0, 52, W, 52), fill=BORDER, width=S)
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        c.d.ellipse(P(24 + i * 22, 20, 36 + i * 22, 32), fill=col)
    c.text(110, 17, "campaigniq.app / campaigns / new", "mono", MUTED)
    # brand mark: the real logo (public/brand/logo-256.webp) as a small rounded tile
    c.img.paste(LOGO, (int((W - 200) * S), int(12 * S)), LOGO_MASK)
    c.text(W - 166, 15, "CampaignIQ", "small", TEXT)


def draw_stepper(c: Canvas, step: int, local: float):
    x0, y0 = 48, 112
    c.text(x0, y0 - 34, "CAMPAIGN LOOP", "tiny", ACCENT)
    for i, name in enumerate(STEPS):
        y = y0 + i * 82
        done = i < step
        current = i == step
        if i < len(STEPS) - 1:
            line_col = ACCENT if i < step else BORDER
            c.d.line(P(x0 + 18, y + 38, x0 + 18, y + 82), fill=line_col, width=2 * S)
        r = 18
        if done:
            c.d.ellipse(P(x0, y, x0 + 2 * r, y + 2 * r), fill=ACCENT)
            c.d.line(P(x0 + 11, y + 19, x0 + 16, y + 24, x0 + 26, y + 13), fill=INK, width=3 * S, joint="curve")
        elif current:
            pulse = 0.5 + 0.5 * math.sin(local * math.pi * 4)
            halo = 6 + 4 * pulse
            c.d.ellipse(P(x0 - halo, y - halo, x0 + 2 * r + halo, y + 2 * r + halo), fill=mix(BG, ACCENT, 0.18))
            c.d.ellipse(P(x0, y, x0 + 2 * r, y + 2 * r), fill=BG, outline=ACCENT, width=3 * S)
            c.text(x0 + r, y + r, str(i + 1), "small", ACCENT, anchor="mm")
        else:
            c.d.ellipse(P(x0, y, x0 + 2 * r, y + 2 * r), fill=RAISED, outline=BORDER, width=2 * S)
            c.text(x0 + r, y + r, str(i + 1), "small", MUTED, anchor="mm")
        c.text(x0 + 52, y + 7, name, "body", TEXT if (done or current) else MUTED)


def panel(c: Canvas, appear: float):
    """Main card; slides up as each scene enters."""
    a = ease(appear)
    dy = (1 - a) * 18
    x, y, w, h = 360, 96 + dy, 880, 584
    c.rect(x, y, w, h, SURFACE, r=22, outline=BORDER)
    return x + 36, y + 32, a


def fade(col, a):
    return mix(SURFACE, col, a)


def scene_idea(c, x, y, a, lt):
    c.text(x, y, "New campaign", "h1", fade(TEXT, a))
    c.text(x, y + 46, "Describe the product and who it's for.", "body", fade(MUTED, a))
    c.rect(x, y + 96, 808, 120, BG, r=16, outline=ACCENT if lt > 0.15 else BORDER, width=2)
    n = int(len(IDEA) * ease((lt - 0.1) / 0.75))
    typed = IDEA[:n]
    c.text(x + 22, y + 126, typed, "h2", fade(TEXT, a))
    if int(lt * 6) % 2 == 0 or n < len(IDEA):
        cx = x + 24 + c.tw(typed, "h2")
        c.d.line(P(cx, y + 126, cx, y + 156), fill=ACCENT, width=2 * S)
    c.text(x + 22, y + 182, f"{n} characters", "tiny", fade(MUTED, a))
    # language + create button
    c.rect(x, y + 246, 180, 48, BG, r=12, outline=BORDER)
    c.text(x + 18, y + 259, "English  v", "small", fade(TEXT, a))
    pressed = ease((lt - 0.92) / 0.08)
    bx = x + 808 - 230
    c.rect(bx - 6 * pressed, y + 246 - 6 * pressed, 230 + 12 * pressed, 48 + 12 * pressed, mix(SURFACE, ACCENT, 0.25 * pressed), r=30)
    c.rect(bx, y + 246, 230, 48, fade(ACCENT, a), r=24)
    c.text(bx + 115, y + 270, "Create campaign  ->", "body", INK, anchor="mm")
    for i, ex in enumerate(["AI budgeting for freelancers", "Eco cleaning refills"]):
        cx = x + i * 260
        c.rect(cx, y + 330, 240, 38, RAISED, r=19, outline=BORDER)
        c.text(cx + 120, y + 349, ex, "tiny", fade(MUTED, a), anchor="mm")


def scene_feasibility(c, x, y, a, lt):
    c.text(x, y, "Feasibility score", "h1", fade(TEXT, a))
    c.text(x, y + 46, "Live market signals, scored and explained.", "body", fade(MUTED, a))
    cx, cy, r = x + 130, y + 250, 105
    c.d.ellipse(P(cx - r, cy - r, cx + r, cy + r), outline=BG, width=18 * S)
    score = 78 * ease(lt / 0.8)
    if score > 0.5:
        c.d.arc(P(cx - r, cy - r, cx + r, cy + r), start=-90, end=-90 + 360 * score / 100, fill=ACCENT, width=18 * S)
    c.text(cx, cy - 8, f"{int(round(score))}", "big", fade(TEXT, a), anchor="mm")
    c.text(cx, cy + 40, "out of 100", "small", fade(MUTED, a), anchor="mm")
    sx = x + 320
    for i, (name, val) in enumerate([("Google Trends", 62), ("News volume", 84), ("Community", 71)]):
        yy = y + 140 + i * 74
        prog = ease((lt - 0.1 - i * 0.12) / 0.6)
        c.text(sx, yy, name, "body", fade(TEXT, a))
        c.text(sx + 470, yy, f"{int(val * prog)}", "body", fade(TEXT, a), anchor="ra")
        c.rect(sx, yy + 32, 470, 10, BG, r=5)
        if prog > 0.01:
            c.rect(sx, yy + 32, 470 * val / 100 * prog, 10, ACCENT, r=5)
    c.rect(sx, y + 380, 470, 70, RAISED, r=12)
    c.text(sx + 18, y + 394, "Strong search momentum and steady news", "small", fade(MUTED, a))
    c.text(sx + 18, y + 418, "coverage; community interest is growing.", "small", fade(MUTED, a))


PERSONAS = [
    ("PR", "Priya, 29", "ICU nurse, rotating nights", "Bluesky", True),
    ("MJ", "Marcus, 34", "ER nurse, 12-hour shifts", "Email", False),
    ("DL", "Dana, 41", "Charge nurse, two kids", "Email", False),
]


def scene_personas(c, x, y, a, lt):
    c.text(x, y, "Audience personas", "h1", fade(TEXT, a))
    c.text(x, y + 46, "Grounded in the research. One drives the round.", "body", fade(MUTED, a))
    for i, (ini, name, desc, chan, primary) in enumerate(PERSONAS):
        p = ease((lt - i * 0.15) / 0.5)
        if p <= 0:
            continue
        cx = x + i * 276
        cy = y + 120 + (1 - p) * 30
        col = mix(SURFACE, RAISED, p)
        c.rect(cx, cy, 256, 300, col, r=18, outline=mix(SURFACE, ACCENT if primary else BORDER, p), width=2)
        c.rect(cx + 22, cy + 24, 56, 56, mix(SURFACE, BG, p), r=14)
        c.text(cx + 50, cy + 52, ini, "h2", mix(SURFACE, ACCENT, p), anchor="mm")
        c.text(cx + 22, cy + 100, name, "h2", mix(SURFACE, TEXT, p))
        c.text(cx + 22, cy + 134, desc, "small", mix(SURFACE, MUTED, p))
        c.text(cx + 22, cy + 190, "Channel", "tiny", mix(SURFACE, MUTED, p))
        c.text(cx + 22, cy + 210, chan, "body", mix(SURFACE, TEXT, p))
        if primary:
            c.rect(cx + 22, cy + 252, 92, 28, mix(SURFACE, ACCENT, p), r=14)
            c.text(cx + 68, cy + 266, "PRIMARY", "tiny", INK, anchor="mm")


def scene_gate(c, x, y, a, lt):
    c.text(x, y, "Gate 2 - review creative", "h1", fade(TEXT, a))
    c.text(x, y + 46, "Nothing is posted until you approve it.", "body", fade(MUTED, a))
    # ad image thumbnail (simple sunrise scene), drawn on its own tile and
    # pasted through a rounded mask so the hills can't spill past the frame
    ix, iy, s = x, y + 110, 250
    tile = Image.new("RGB", (s * S, s * S), mix(SURFACE, (60, 38, 30), a))
    td = ImageDraw.Draw(tile)
    td.ellipse(P(140, 50, 200, 110), fill=fade(ACCENT, a))
    td.ellipse(P(-60, 170, 200, 330), fill=fade((44, 50, 60), a))
    td.ellipse(P(80, 190, 340, 360), fill=fade((70, 78, 90), a))
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s * S - 1, s * S - 1), radius=18 * S, fill=255)
    c.img.paste(tile, (int(ix * S), int(iy * S)), mask)
    c.rect(ix, iy, s, s, None, r=18, outline=BORDER)
    tx = x + 280
    c.rect(tx, y + 110, 528, 120, RAISED, r=14)
    c.d.rectangle(P(tx, y + 116, tx + 4, y + 224), fill=fade(ACCENT, a))
    c.text(tx + 24, y + 132, "Night shift ends at 7.", "h2", fade(TEXT, a))
    c.text(tx + 24, y + 166, "Dinner's already handled. Fresh meals, ready", "small", fade(MUTED, a))
    c.text(tx + 24, y + 190, "when you are.", "small", fade(MUTED, a))
    c.text(tx, y + 258, "Pre-flight", "small", fade(MUTED, a))
    c.rect(tx + 90, y + 264, 380, 10, BG, r=5)
    c.rect(tx + 90, y + 264, 380 * 0.82 * ease(lt / 0.5), 10, ACCENT, r=5)
    c.text(tx + 528, y + 256, "82", "body", fade(TEXT, a), anchor="ra")
    press = ease((lt - 0.55) / 0.15)
    approved = lt > 0.72
    by = y + 400
    if approved:
        c.rect(x, by, 300, 54, fade(SUCCESS, a), r=27)
        c.text(x + 150, by + 27, "Approved - publishing", "body", INK, anchor="mm")
    else:
        grow = 4 * press
        c.rect(x - grow, by - grow, 160 + 2 * grow, 54 + 2 * grow, fade(ACCENT, a), r=27)
        c.text(x + 80, by + 27, "Approve", "body", INK, anchor="mm")
        c.rect(x + 176, by, 110, 54, RAISED, r=27, outline=BORDER)
        c.text(x + 231, by + 27, "Edit", "body", fade(TEXT, a), anchor="mm")
        c.rect(x + 302, by, 120, 54, SURFACE, r=27, outline=(120, 50, 60))
        c.text(x + 362, by + 27, "Reject", "body", (255, 84, 112), anchor="mm")


def scene_publish(c, x, y, a, lt):
    c.text(x, y, "Published", "h1", fade(TEXT, a))
    c.text(x, y + 46, "Real posts and real email, tracked through our own redirect.", "body", fade(MUTED, a))
    rows = [("Bluesky", "Post live", "likes", 48), ("Email", "Delivered to 120", "clicks", 19)]
    for i, (name, status, unit, target) in enumerate(rows):
        p = ease((lt - i * 0.2) / 0.45)
        if p <= 0:
            continue
        ry = y + 130 + i * 120
        c.rect(x, ry, 808, 96, mix(SURFACE, RAISED, p), r=18)
        c.rect(x + 22, ry + 22, 52, 52, mix(SURFACE, BG, p), r=14)
        c.text(x + 48, ry + 48, name[0], "h2", mix(SURFACE, ACCENT, p), anchor="mm")
        c.text(x + 96, ry + 24, name, "h2", mix(SURFACE, TEXT, p))
        c.d.ellipse(P(x + 96, ry + 62, x + 112, ry + 78), fill=mix(SURFACE, SUCCESS, p))
        c.text(x + 120, ry + 59, status, "small", mix(SURFACE, MUTED, p))
        count = round(target * ease((lt - 0.3 - i * 0.15) / 0.6))
        c.text(x + 780, ry + 30, f"{count}", "num", mix(SURFACE, TEXT, p), anchor="ra")
        c.text(x + 780, ry + 64, unit, "tiny", mix(SURFACE, MUTED, p), anchor="ra")


REWARDS = [0.18, 0.31, 0.29, 0.52, 0.74]


def scene_learn(c, x, y, a, lt):
    c.text(x, y, "Reward by round", "h1", fade(TEXT, a))
    c.text(x, y + 46, "The bandit shifts toward what real engagement rewards.", "body", fade(MUTED, a))
    gx, gy, gw, gh = x + 40, y + 110, 740, 270
    for v in (0.0, 0.5, 1.0):
        yy = gy + gh * (1 - v)
        c.d.line(P(gx, yy, gx + gw, yy), fill=BORDER, width=S)
        c.text(gx - 14, yy - 9, f"{v:.1f}", "mono", MUTED, anchor="ra")
    prog = ease(lt / 0.65) * (len(REWARDS) - 1)
    pts = [(gx + i * gw / (len(REWARDS) - 1), gy + gh * (1 - r)) for i, r in enumerate(REWARDS)]
    drawn = [pts[0]]
    for i in range(1, len(pts)):
        seg = max(0.0, min(1.0, prog - (i - 1)))
        if seg <= 0:
            break
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        drawn.append((x0 + (x1 - x0) * seg, y0 + (y1 - y0) * seg))
    if len(drawn) > 1:
        poly = drawn + [(drawn[-1][0], gy + gh), (gx, gy + gh)]
        c.d.polygon([v * S for pt in poly for v in pt], fill=mix(SURFACE, ACCENT, 0.16))
        c.d.line([v * S for pt in drawn for v in pt], fill=ACCENT, width=4 * S, joint="curve")
    for i, (px, py) in enumerate(pts):
        if i <= prog + 0.01:
            r = 9 if i == len(pts) - 1 else 7
            c.d.ellipse(P(px - r, py - r, px + r, py + r), fill=ACCENT, outline=SURFACE, width=3 * S)
        c.text(px, gy + gh + 16, f"R{i + 1}", "mono", MUTED, anchor="ma")
    arm = ease((lt - 0.6) / 0.25)
    if arm > 0:
        c.rect(x, y + 440, 808, 60, mix(SURFACE, RAISED, arm), r=14)
        c.text(x + 22, y + 459, "Winning arm", "small", mix(SURFACE, MUTED, arm))
        c.text(x + 150, y + 456, "Lifestyle x humorous", "h2", mix(SURFACE, TEXT, arm))
        c.rect(x + 690, y + 454, 96, 32, mix(SURFACE, ACCENT, arm), r=8)
        c.text(x + 738, y + 470, "0.74", "body", INK, anchor="mm")


DRAW = [scene_idea, scene_feasibility, scene_personas, scene_gate, scene_publish, scene_learn]


def render(t: float) -> Image.Image:
    c = Canvas()
    draw_chrome(c)
    step, local, elapsed = scene_progress(t)
    draw_stepper(c, step, local)
    x, y, a = panel(c, elapsed / 0.3)
    DRAW[step](c, x, y, a, min(1.0, local / ACTION_SHARE))
    img = c.img.resize((W, H), Image.LANCZOS)
    # Fade the last 0.5 s into the first frame so the loop has no seam.
    tail = DURATION - 0.5
    if t > tail:
        first = FIRST if FIRST is not None else img
        img = Image.blend(img, first, ease((t - tail) / 0.5))
    return img


FIRST = None
if __name__ == "__main__":
    out = sys.argv[1]
    FIRST = render(0.0)
    frames = [render(i / FPS) for i in range(FRAMES)]
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(1000 / FPS), loop=0, quality=80, method=4)
    frames[int(FPS * 5.2)].save(out.replace(".webp", "-poster.webp"), quality=82)
    print(f"{len(frames)} frames, {DURATION}s @ {FPS}fps -> {out}")
