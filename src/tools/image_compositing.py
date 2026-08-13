import io

from PIL import Image

CORNER_MARGIN = 24
CORNER_SIZE_FRACTION = 0.28


def overlay_template(base_image_bytes: bytes, template_bytes: bytes) -> bytes:
    """Free-tier fallback when a template is provided but the resolved image
    provider can't outpaint: composite the template as a corner overlay on
    top of a freshly generated image, rather than silently ignoring it."""
    base = Image.open(io.BytesIO(base_image_bytes)).convert("RGBA")
    template = Image.open(io.BytesIO(template_bytes)).convert("RGBA")

    corner_size = int(min(base.width, base.height) * CORNER_SIZE_FRACTION)
    template.thumbnail((corner_size, corner_size))

    position = (base.width - template.width - CORNER_MARGIN, base.height - template.height - CORNER_MARGIN)
    base.alpha_composite(template, position)

    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()
