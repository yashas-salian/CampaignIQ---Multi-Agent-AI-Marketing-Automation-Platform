import html as html_lib

from src.capabilities.distribution import send_campaign_email
from src.capabilities.guardrails import DISCLAIMERS, prepare_for_channel
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
    domain = state.get("domain_category", "other")
    text, blocked = prepare_for_channel(creative.copy_text, "email", domain_category=domain, cta_url=state.get("cta_url"))
    if blocked:
        email_id = f"dead: {blocked}"
    else:
        body = _render_email_html(text, state)
        disclaimer = DISCLAIMERS.get(domain)
        if disclaimer:
            body += f'<p style="font-size:12px;color:#666">{html_lib.escape(disclaimer)}</p>'
        email_id = send_campaign_email(
            state["campaign_id"],
            state["round_id"],
            state["email_to"],
            subject=state["idea"][:78],
            html=body,
            cta_url=state.get("cta_url"),
            user_id=state["user_id"],
        )
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], email_id=email_id)
    return {"email_id": email_id}
