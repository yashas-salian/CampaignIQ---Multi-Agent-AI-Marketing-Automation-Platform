"""A campaign's product: its photo cut out for the ad templates, and its tagline.

The cut-out is made once per campaign (rembg is slow to load) and kept next
to the campaign's ads as {campaign_id}/product-cutout.png; later rounds and
Gate 2's "New picture" reuse it.
"""
import logging
from dataclasses import dataclass

logger = logging.getLogger("capabilities.product")

PRODUCT_PHOTOS_BUCKET = "product-photos"


@dataclass
class Product:
    cutout: bytes | None  # trimmed RGBA PNG, or None when the campaign has no usable photo
    tagline: str = ""
    template: str = ""  # the ad template the creator picked for every round, or "" (best fit each round)


def cutout_path(campaign_id: str) -> str:
    return f"{campaign_id}/product-cutout.png"


def product_for_campaign(campaign_id: str | None) -> Product:
    """The campaign's product. Never raises: without a usable photo the
    creative step falls back to an image-model picture."""
    if not campaign_id:
        return Product(None)
    try:
        from src.db.supabase_client import get_client

        row = (
            get_client().table("campaigns").select("product_image_path,product_tagline,ad_template")
            .eq("id", campaign_id).maybe_single().execute()
        )
        row = (row.data if row else None) or {}
    except Exception as exc:
        logger.warning("reading the campaign's product failed: %s", exc)
        return Product(None)
    from src.tools.ad_templates import TEMPLATES

    tagline = (row.get("product_tagline") or "").strip()
    template = row.get("ad_template") if row.get("ad_template") in TEMPLATES else ""
    if not row.get("product_image_path"):
        return Product(None, tagline, template)
    return Product(_cutout(campaign_id, row["product_image_path"]), tagline, template)


def _cutout(campaign_id: str, photo_path: str) -> bytes | None:
    from src.db.supabase_client import AD_IMAGES_BUCKET, download_object, get_client

    try:
        return download_object(AD_IMAGES_BUCKET, cutout_path(campaign_id))
    except Exception:
        pass  # not made yet
    try:
        from src.tools.product_cutout import cutout

        made = cutout(download_object(PRODUCT_PHOTOS_BUCKET, photo_path))
    except Exception as exc:
        logger.warning("product photo unavailable: %s", exc)
        return None
    try:
        get_client().storage.from_(AD_IMAGES_BUCKET).upload(
            cutout_path(campaign_id), made, {"content-type": "image/png", "upsert": "true"}
        )
    except Exception as exc:  # caching is an optimisation: the next round just cuts it out again
        logger.warning("storing the product cut-out failed: %s", exc)
    return made
