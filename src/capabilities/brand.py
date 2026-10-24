"""An organisation's brand kit (brand_kits table), as used by the pipeline."""
import logging

from pydantic import BaseModel

from src.security.prompt_guard import fence

logger = logging.getLogger("capabilities.brand")


class BrandKit(BaseModel):
    voice: str = ""
    preferred_words: list[str] = []
    forbidden_words: list[str] = []
    required_phrase: str | None = None
    brand_color: str | None = None
    # In the private brand-logos bucket ({org_id}/logo-....png), set in Settings -> Brand kit.
    logo_path: str | None = None

    @property
    def empty(self) -> bool:
        return not (self.voice.strip() or self.preferred_words or self.forbidden_words or self.required_phrase)

    def prompt_section(self) -> str:
        """Brand guidance for the creative prompt ("" when there's no kit).
        The voice is user-written text, so it's fenced like any other."""
        if self.empty:
            return ""
        lines = ["Brand guidelines (follow them):"]
        if self.voice.strip():
            lines.append(f"Voice:\n{fence(self.voice, 'brand_voice', max_len=1000)}")
        if self.preferred_words:
            lines.append("Prefer these words where natural: " + ", ".join(self.preferred_words[:30]))
        if self.forbidden_words:
            lines.append("Never use these words: " + ", ".join(self.forbidden_words[:100]))
        if self.required_phrase:
            lines.append(f'End the copy with: "{self.required_phrase}"')
        return "\n".join(lines) + "\n"


def with_required_phrase(text: str, kit: BrandKit | None, *, max_len: int | None = None) -> str:
    """Append the kit's required sign-off if the copy lacks it (and it fits)."""
    if not kit or not kit.required_phrase or kit.required_phrase.lower() in text.lower():
        return text
    combined = f"{text.rstrip()} {kit.required_phrase}"
    return text if max_len is not None and len(combined) > max_len else combined


BRAND_LOGOS_BUCKET = "brand-logos"


def brand_logo(kit: BrandKit | None) -> bytes | None:
    """The kit's logo image, or None. Never raises: a missing logo just leaves
    the ad without one."""
    if not kit or not kit.logo_path:
        return None
    try:
        from src.db.supabase_client import download_object

        return download_object(BRAND_LOGOS_BUCKET, kit.logo_path)
    except Exception as exc:
        logger.warning("brand logo download failed: %s", exc)
        return None


def brand_kit_for_campaign(campaign_id: str | None) -> BrandKit | None:
    """The kit of the campaign's organisation, or None. Never raises."""
    if not campaign_id:
        return None
    try:
        from src.db.supabase_client import get_client

        client = get_client()
        campaign = client.table("campaigns").select("org_id").eq("id", campaign_id).maybe_single().execute()
        if not campaign or not campaign.data:
            return None
        row = client.table("brand_kits").select("*").eq("org_id", campaign.data["org_id"]).maybe_single().execute()
        return BrandKit(**{k: v for k, v in (row.data or {}).items() if k in BrandKit.model_fields}) if row and row.data else None
    except Exception as exc:
        logger.warning("brand kit lookup failed for %s: %s", campaign_id, exc)
        return None
