from src.capabilities.brand import brand_kit_for_campaign
from src.capabilities.brand_memory import allowed_arm, context_from_state, recall
from src.capabilities.creative import arm_for_template, generate_creative
from src.capabilities.playbooks import playbook_section_for_campaign
from src.capabilities.product import product_for_campaign
from src.constants import active_channels
from src.graph.state import CampaignState


def creative_node(state: CampaignState) -> CampaignState:
    # Straight after a decided A/B test, the next round runs the winner's arm.
    promoted = state.get("promote_arm")
    product = product_for_campaign(state.get("campaign_id"))
    arm = (int(promoted[0]), str(promoted[1]), str(promoted[2])) if promoted else None
    directive = state.get("revision_directive")
    # A creative-fatigue refresh waiting for this round: change the repeated
    # feature (the result still goes through every check and Gate 2).
    refresh, refresh_arm = _refresh(state)
    if refresh:
        directive = f"{directive}\n{refresh}" if directive else refresh
        arm = refresh_arm or arm
    # Brand memory: background lessons for the prompt, plus directives that can only make it
    # stricter (more banned words; remembered tones and styles to avoid when picking the arm).
    memory = recall(context_from_state(state, persona=state.get("primary_persona"), channels=active_channels()))
    avoids = memory.directives.get("avoid_tones") or memory.directives.get("avoid_styles")
    if arm is None and avoids and state.get("primary_persona") is not None:
        arm = allowed_arm(_candidate_arms(state), memory.directives)
    # A template the creator picked holds for every round: the arm keeps its
    # style, and the template is drawn as chosen.
    template = product.template or None
    if template:
        arm = arm_for_template(template, _candidate_arms(state), arm)
    return {
        "promote_arm": None,
        "creative": generate_creative(
            state["idea"],
            state["primary_persona"],
            domain_category=state["domain_category"],
            active_channels=active_channels(),
            user_id=state.get("user_id"),
            use_image_template=state.get("use_image_template", False),
            revision_directive=directive,
            target_language=state.get("target_language", "en"),
            cta_url=state.get("cta_url"),
            brand=brand_kit_for_campaign(state.get("campaign_id")),
            playbook=playbook_section_for_campaign(state.get("campaign_id")),
            memory=memory.section,
            banned_terms=tuple(memory.directives.get("avoid_terms") or ()),
            arm=arm,
            product_cutout=product.cutout,
            tagline=product.tagline,
            template=template,
        ),
    }


def _candidate_arms(state: CampaignState) -> list[tuple[int, str, str]]:
    from src.tools.bandit import select_arms_for_campaign

    persona = state["primary_persona"]
    try:
        return select_arms_for_campaign(persona.age_bracket, persona.income_tier, state["domain_category"], active_channels(), k=20)
    except Exception:
        return []


def _refresh(state: CampaignState):
    if not state.get("campaign_id") or (state.get("round_id") or 1) <= 1:
        return None, None
    from src.capabilities.fatigue import apply_pending_refresh
    from src.tools.bandit import select_arms_for_campaign

    persona = state["primary_persona"]
    return apply_pending_refresh(
        state["campaign_id"], state["round_id"],
        candidates_fn=lambda: select_arms_for_campaign(persona.age_bracket, persona.income_tier, state["domain_category"],
                                                       active_channels(), k=20),
    )
