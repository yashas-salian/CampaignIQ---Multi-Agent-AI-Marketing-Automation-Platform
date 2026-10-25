from src.capabilities.brand import brand_kit_for_campaign
from src.capabilities.creative import generate_creative
from src.capabilities.playbooks import playbook_section_for_campaign
from src.capabilities.product import product_for_campaign
from src.constants import active_channels
from src.graph.state import CampaignState


def creative_node(state: CampaignState) -> CampaignState:
    # Straight after a decided A/B test, the next round runs the winner's arm.
    promoted = state.get("promote_arm")
    product = product_for_campaign(state.get("campaign_id"))
    return {
        "promote_arm": None,
        "creative": generate_creative(
            state["idea"],
            state["primary_persona"],
            domain_category=state["domain_category"],
            active_channels=active_channels(),
            user_id=state.get("user_id"),
            use_image_template=state.get("use_image_template", False),
            revision_directive=state.get("revision_directive"),
            target_language=state.get("target_language", "en"),
            cta_url=state.get("cta_url"),
            brand=brand_kit_for_campaign(state.get("campaign_id")),
            playbook=playbook_section_for_campaign(state.get("campaign_id")),
            arm=(int(promoted[0]), str(promoted[1]), str(promoted[2])) if promoted else None,
            product_cutout=product.cutout,
            tagline=product.tagline,
        ),
    }
