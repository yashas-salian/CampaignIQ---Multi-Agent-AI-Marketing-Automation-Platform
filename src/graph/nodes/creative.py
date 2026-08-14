from src.capabilities.creative import generate_creative
from src.constants import active_channels
from src.graph.state import CampaignState


def creative_node(state: CampaignState) -> CampaignState:
    return {
        "creative": generate_creative(
            state["idea"],
            state["primary_persona"],
            domain_category=state["domain_category"],
            active_channels=active_channels(),
            user_id=state.get("user_id"),
            use_image_template=state.get("use_image_template", False),
            revision_directive=state.get("revision_directive"),
            target_language=state.get("target_language", "en"),
        )
    }
