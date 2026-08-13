from src.capabilities.creative import generate_creative
from src.graph.state import CampaignState


def creative_node(state: CampaignState) -> CampaignState:
    return {
        "creative": generate_creative(
            state["idea"],
            state["primary_persona"],
            user_id=state.get("user_id"),
            use_image_template=state.get("use_image_template", False),
            revision_directive=state.get("revision_directive"),
        )
    }
