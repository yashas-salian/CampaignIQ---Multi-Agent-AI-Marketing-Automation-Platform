"""Cut the campaign's product photo out of its background, so the templates
(src/tools/ad_templates.py) can set the real product into any layout.

A photo that already has transparency (a PNG cut-out) is kept as it is.
Otherwise the IS-Net "general use" segmentation model (the one rembg ships)
runs on onnxruntime to find the product. The model (~180 MB) is downloaded
once to ~/.u2net and cached by the campaign workflow. If onnxruntime is
missing, the model can't load, or no clear subject is found, the whole photo
is used on a rounded white card instead: a flaky cut-out never fails a round.
"""
import io
import logging
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger("tools.product_cutout")

MODEL_URL = "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx"
MODEL_PATH = Path(os.environ.get("U2NET_HOME", Path.home() / ".u2net")) / "isnet-general-use.onnx"
MODEL_SIDE = 1024  # the model's input size
MAX_SIDE = 1400  # plenty for a 1080 ad
# A cut-out keeping less than this share of the photo found no real subject.
MIN_SUBJECT_SHARE = 0.03
# Share of the subject the model is sure about. A clean product shot scores
# 0.9+; a close-up that fills the frame (nothing to cut away) gives a patchy,
# see-through mask far below this, and is better shown whole on a card.
MIN_SOLID_SHARE = 0.6


def _download_model() -> None:
    import requests

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    partial = MODEL_PATH.with_suffix(".part")
    with requests.get(MODEL_URL, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(partial, "wb") as out:
            for chunk in response.iter_content(1 << 20):
                out.write(chunk)
    partial.replace(MODEL_PATH)


@lru_cache(maxsize=1)
def _session():
    import onnxruntime

    if not MODEL_PATH.exists():
        _download_model()
    return onnxruntime.InferenceSession(str(MODEL_PATH), providers=["CPUExecutionProvider"])


def _mask(image: Image.Image) -> Image.Image:
    """The model's foreground mask (L, 0-255) at the photo's size."""
    import numpy as np

    session = _session()
    small = image.convert("RGB").resize((MODEL_SIDE, MODEL_SIDE), Image.BILINEAR)
    x = np.asarray(small, dtype=np.float32)
    x = x / max(float(x.max()), 1e-6) - 0.5  # IS-Net's normalisation: scale to 0-1, mean 0.5, std 1
    x = x.transpose(2, 0, 1)[None]
    pred = session.run(None, {session.get_inputs()[0].name: x})[0][0, 0]
    lo, hi = float(pred.min()), float(pred.max())
    pred = (pred - lo) / max(hi - lo, 1e-6)
    return Image.fromarray((pred * 255).astype("uint8"), "L").resize(image.size, Image.LANCZOS)


def _remove_background(image: Image.Image) -> Image.Image:
    mask = _mask(image)
    # Firm up the soft model output: clear haze, keep edges a touch soft.
    mask = mask.point(lambda v: 0 if v < 40 else (255 if v > 215 else round((v - 40) * 255 / 175)))
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def _has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "P"):
        return False
    return image.convert("RGBA").getchannel("A").getextrema()[0] < 250


def _trim(image: Image.Image) -> Image.Image:
    box = image.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    return image.crop(box) if box else image


def card(image: Image.Image) -> Image.Image:
    """The whole photo on a white rounded card (the fallback)."""
    image = image.convert("RGB")
    pad = round(max(image.size) * 0.04)
    w, h = image.width + 2 * pad, image.height + 2 * pad
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=round(min(w, h) * 0.06), fill=255)
    out.paste((255, 255, 255, 255), (0, 0, w, h), mask)
    inner = Image.new("L", image.size, 0)
    ImageDraw.Draw(inner).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius=round(min(image.size) * 0.04), fill=255)
    out.paste(image, (pad, pad), inner)
    return out


def cutout(photo: bytes) -> bytes:
    """The product as a trimmed RGBA PNG."""
    image = Image.open(io.BytesIO(photo))
    image.load()
    image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    if _has_transparency(image):
        result = _trim(image.convert("RGBA"))
    else:
        try:
            removed = _remove_background(image)
            alpha = removed.getchannel("A")
            subject = sum(alpha.point(lambda v: 1 if v > 128 else 0).getdata())
            share = subject / (alpha.width * alpha.height)
            if share < MIN_SUBJECT_SHARE:
                raise ValueError(f"no clear subject ({share:.1%} of the photo)")
            solid = sum(alpha.point(lambda v: 1 if v > 215 else 0).getdata()) / max(1, subject)
            if solid < MIN_SOLID_SHARE:
                raise ValueError(f"unsure where the product ends ({solid:.0%} solid)")
            removed.putalpha(alpha.filter(ImageFilter.GaussianBlur(0.6)))
            result = _trim(removed)
        except Exception as exc:
            logger.warning("background removal failed, using the photo on a card: %s", exc)
            result = card(image)
    out = io.BytesIO()
    result.save(out, format="PNG", optimize=True)
    return out.getvalue()
