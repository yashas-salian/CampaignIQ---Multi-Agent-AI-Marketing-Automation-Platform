import logging

from src.capabilities.crash_test import AdText, run_for_round
from src.graph.state import CampaignState

logger = logging.getLogger("graph.crash_test")


def crash_test_node(state: CampaignState) -> CampaignState:
    """How could this ad fail? Rule checks and simulated scenarios on the final
    draft, then a revised version when something is high or critical; the
    report waits for the approver at Gate 2. Advice and a gate rule, never a
    step that can stop the campaign by failing."""
    creative = state.get("creative")
    if creative is None:
        return {}
    try:
        ad = AdText(body=creative.copy_text, headline=creative.headline, cta=creative.cta, visual=creative.image_prompt)
        run_for_round(state["campaign_id"], state["round_id"], user_id=state.get("user_id"), ad=ad, idea=state.get("idea"))
    except Exception as exc:  # never block the gate on the crash test itself
        logger.warning("crash test skipped for %s: %s", state.get("campaign_id"), exc)
    return {}
