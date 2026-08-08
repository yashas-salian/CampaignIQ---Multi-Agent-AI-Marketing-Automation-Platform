from src.capabilities.distribution import send_campaign_email
from src.graph.state import CampaignState


def distribution_email_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    email_id = send_campaign_email(
        state["campaign_id"],
        state["round_id"],
        state["email_to"],
        subject=state["idea"][:78],
        html=f"<p>{creative.copy_text}</p>",
        cta_url=state.get("cta_url"),
    )
    return {"email_id": email_id}
