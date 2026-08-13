from src.capabilities.distribution import send_campaign_email
from src.db.supabase_client import get_template, upsert_iteration
from src.graph.state import CampaignState


def _render_email_html(copy_text: str, state: CampaignState) -> str:
    user_id = state.get("user_id")
    if state.get("use_email_template") and user_id:
        template = get_template(user_id, "email")
        if template and template.get("email_html"):
            # The stored template is a full layout with a "{{copy}}" placeholder
            # for the generated ad copy to be dropped into.
            return template["email_html"].replace("{{copy}}", copy_text)
    return f"<p>{copy_text}</p>"


def distribution_email_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    email_id = send_campaign_email(
        state["campaign_id"],
        state["round_id"],
        state["email_to"],
        subject=state["idea"][:78],
        html=_render_email_html(creative.copy_text, state),
        cta_url=state.get("cta_url"),
    )
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], email_id=email_id)
    return {"email_id": email_id}
