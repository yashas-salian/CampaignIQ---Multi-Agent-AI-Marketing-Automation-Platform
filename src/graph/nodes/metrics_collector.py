import logging

from src.capabilities.metrics import collect_metrics
from src.db.supabase_client import get_client, update_campaign
from src.graph.state import CampaignState

log = logging.getLogger(__name__)


def metrics_collector_node(state: CampaignState) -> CampaignState:
    result = collect_metrics(state["campaign_id"], state["user_id"], state["round_id"], email_to=state.get("email_to"))
    out: CampaignState = {"metrics_result": result}

    # Bayesian early stop: once one email variant is clearly better, stop
    # splitting the list and send everyone the winner's style from now on.
    bayes = (result.raw.get("email_b", {}).get("ab_test") or {}).get("bayes") or {}
    winner = bayes.get("decided")
    if winner and state.get("ab_test"):
        creative = state["creative"] if winner == "a" else state.get("creative_b")
        if creative is not None:
            decision = {
                "winner": winner,
                "prob_b_beats_a": bayes["prob_b_beats_a"],
                "round": state["round_id"],
                "arm_index": creative.arm_index,
                "image_style": creative.image_style,
                "copy_tone": creative.copy_tone,
            }
            update_campaign(state["campaign_id"], ab_test=False, ab_decision=decision)
            _announce(state, decision)
            out.update(ab_test=False, creative_b=None, promote_arm=[creative.arm_index, creative.image_style, creative.copy_tone])
    return out


def _announce(state: CampaignState, decision: dict) -> None:
    # Audit log entry, which also fans out to the organisation's webhooks.
    if not state.get("org_id"):
        return
    try:
        get_client().rpc("audit", {
            "p_org": state["org_id"], "p_action": "experiment.decided", "p_target_type": "campaign",
            "p_target_id": state["campaign_id"], "p_details": decision,
        }).execute()
    except Exception as exc:  # a missed announcement never undoes the decision
        log.warning("experiment.decided not audited: %s", exc)
