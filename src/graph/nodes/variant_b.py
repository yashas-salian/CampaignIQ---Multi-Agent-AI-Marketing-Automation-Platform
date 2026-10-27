from src.capabilities.brand import brand_kit_for_campaign
from src.capabilities.creative import arm_for_template, generate_creative
from src.capabilities.product import product_for_campaign
from src.constants import active_channels
from src.db.supabase_client import upsert_iteration
from src.graph.state import CampaignState
from src.tools.bandit import select_arms_for_campaign


def generate_variant_b_node(state: CampaignState) -> CampaignState:
    """A/B-tested campaigns: write variant B with the bandit's second-best arm.

    Its own step between pre-flight and Gate 2 (not inside the gate, which
    re-runs on resume), so the B the approver sees is the B that's sent. Only
    for email with at least two recipients: the list is split in halves.
    """
    channels = active_channels()
    if not state.get("ab_test") or "email" not in channels or len(state.get("email_to") or []) < 2:
        return {"creative_b": None}
    persona = state["primary_persona"]
    product = product_for_campaign(state.get("campaign_id"))
    if product.template:
        # The creator's template holds for B too: the second-best tone in its style.
        ranked = select_arms_for_campaign(persona.age_bracket, persona.income_tier, state["domain_category"], channels, k=20)
        family = arm_for_template(product.template, ranked)[1]
        in_style = [a for a in ranked if a[1] == family]
        arm_b = in_style[1] if len(in_style) > 1 else arm_for_template(product.template, ranked)
    else:
        arm_b = select_arms_for_campaign(persona.age_bracket, persona.income_tier, state["domain_category"], channels, k=2)[-1]
    variant = generate_creative(
        state["idea"],
        persona,
        domain_category=state["domain_category"],
        active_channels=["email"],
        user_id=state.get("user_id"),
        revision_directive=state.get("revision_directive"),
        target_language=state.get("target_language", "en"),
        cta_url=state.get("cta_url"),
        brand=brand_kit_for_campaign(state.get("campaign_id")),
        arm=arm_b,
        product_cutout=product.cutout,
        tagline=product.tagline,
        template=product.template or None,
    )
    upsert_iteration(
        state["campaign_id"], state["user_id"], state["round_id"],
        copy_text_b=variant.copy_text, image_prompt_b=variant.image_prompt,
        image_style_b=variant.image_style, copy_tone_b=variant.copy_tone, arm_index_b=variant.arm_index,
    )
    return {"creative_b": variant}
