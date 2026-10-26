from src.capabilities.brand import brand_kit_for_campaign, with_required_phrase
from src.capabilities.distribution import post_bluesky
from src.capabilities.email_engine import signup_line, with_signup_line
from src.capabilities.guardrails import BLUESKY_MAX_CHARS, prepare_for_channel
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState


def distribution_bluesky_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    kit = brand_kit_for_campaign(state["campaign_id"])
    copy = with_required_phrase(creative.copy_text, kit, max_len=BLUESKY_MAX_CHARS)
    text, blocked = prepare_for_channel(
        copy, "bluesky", domain_category=state.get("domain_category", "other"), cta_url=state.get("cta_url"),
        banned_terms=kit.forbidden_words if kit else (),
    )
    if blocked:
        uri = f"dead: {blocked}"
    else:
        # The brand's sign-up link (when its email is connected): how interested strangers join its list.
        text = with_signup_line(text, signup_line(state["campaign_id"]), max_len=BLUESKY_MAX_CHARS)
        uri = post_bluesky(state["campaign_id"], state["round_id"], text, image_bytes=creative.image_bytes, user_id=state["user_id"])
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], bluesky_post_uri=uri)
    return {"bluesky_post_uri": uri}
