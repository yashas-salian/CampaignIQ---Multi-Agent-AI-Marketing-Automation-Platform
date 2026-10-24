from src.capabilities.brand import brand_kit_for_campaign, with_required_phrase
from src.capabilities.distribution import post_mastodon
from src.capabilities.guardrails import MASTODON_MAX_CHARS, prepare_for_channel
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState


def distribution_mastodon_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    kit = brand_kit_for_campaign(state["campaign_id"])
    copy = with_required_phrase(creative.copy_text, kit, max_len=MASTODON_MAX_CHARS)
    text, blocked = prepare_for_channel(
        copy, "mastodon", domain_category=state.get("domain_category", "other"), cta_url=state.get("cta_url"),
        banned_terms=kit.forbidden_words if kit else (),
    )
    if blocked:
        url = f"dead: {blocked}"
    else:
        url = post_mastodon(
            state["campaign_id"], state["round_id"], text, image_bytes=creative.image_bytes,
            image_alt=creative.headline or creative.image_prompt, user_id=state["user_id"],
        )
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], mastodon_post_url=url)
    return {"mastodon_post_url": url}
