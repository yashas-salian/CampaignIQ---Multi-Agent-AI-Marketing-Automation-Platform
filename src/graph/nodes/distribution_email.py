import html as html_lib

from src.capabilities.brand import brand_kit_for_campaign, with_required_phrase
from src.capabilities.distribution import send_campaign_email
from src.capabilities.experiments import split_recipients
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
    kit = brand_kit_for_campaign(state["campaign_id"])
    disclaimer = DISCLAIMERS.get(domain)
    text, blocked = prepare_for_channel(
        with_required_phrase(creative.copy_text, kit), "email", domain_category=domain, cta_url=state.get("cta_url"),
        banned_terms=kit.forbidden_words if kit else (),
    )
    if blocked:
        email_id = f"dead: {blocked}"
    else:
        body = _render_email_html(text, state)
        if disclaimer:
            body += f'<p style="font-size:12px;color:#666">{html_lib.escape(disclaimer)}</p>'
        variant = state.get("creative_b")
        recipients_a, recipients_b = split_recipients(state["email_to"]) if variant else (state["email_to"], [])
        email_id = send_campaign_email(
            state["campaign_id"],
            state["round_id"],
            recipients_a,
            subject=state["idea"][:78],
            html=body,
            cta_url=state.get("cta_url"),
            user_id=state["user_id"],
            image_bytes=creative.image_bytes or None,
            image_alt=creative.headline or creative.copy_text[:120],
        )
        if variant and recipients_b:
            text_b, blocked_b = prepare_for_channel(
                with_required_phrase(variant.copy_text, kit), "email", domain_category=domain,
                cta_url=state.get("cta_url"), banned_terms=kit.forbidden_words if kit else (),
            )
            body_b = _render_email_html(text_b, state) if not blocked_b else None
            if body_b and disclaimer:
                body_b += f'<p style="font-size:12px;color:#666">{html_lib.escape(disclaimer)}</p>'
            email_id_b = f"dead: {blocked_b}" if blocked_b else send_campaign_email(
                state["campaign_id"], state["round_id"], recipients_b, subject=state["idea"][:78], html=body_b,
                cta_url=state.get("cta_url"), user_id=state["user_id"], channel="email_b",
                image_bytes=variant.image_bytes or None, image_alt=variant.headline or variant.copy_text[:120],
            )
            upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], email_id_b=email_id_b)
    upsert_iteration(state["campaign_id"], state["user_id"], state["round_id"], email_id=email_id)
    return {"email_id": email_id}
