from src.capabilities.distribution import send_campaign_email
from src.db.supabase_client import upsert_iteration
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
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], email_id=email_id)
    return {"email_id": email_id}
