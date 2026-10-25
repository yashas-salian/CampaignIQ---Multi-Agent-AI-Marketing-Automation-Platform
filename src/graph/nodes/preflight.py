import logging

from src.capabilities.preflight import score_preflight
from src.db.supabase_client import upload_ad_image, upsert_iteration
from src.graph.state import CampaignState

MAX_PREFLIGHT_ATTEMPTS = 3

logger = logging.getLogger("graph.preflight")


def _stored_image(state: CampaignState, image_bytes: bytes, scene: bytes | None = None) -> dict:
    """{"image_path": ...} once the finished ad is stored, else {} (the page
    then falls back to a preview drawn from the prompt). Never fails the round."""
    if not image_bytes:
        return {}
    if scene:  # the template's painted background, for redrawing the ad with revised words
        try:
            upload_ad_image(state["campaign_id"], state["round_id"], scene, variant="scene")
        except Exception as exc:
            logger.warning("storing the ad's background failed: %s", exc)
    try:
        return {"image_path": upload_ad_image(state["campaign_id"], state["round_id"], image_bytes)}
    except Exception as exc:
        logger.warning("storing the ad image failed: %s", exc)
        return {}


def preflight_node(state: CampaignState) -> CampaignState:
    creative = state["creative"]
    result = score_preflight(
        creative, [state["primary_persona"]], user_id=state.get("user_id"),
        target_language=state.get("target_language", "en"),
    )
    attempt = state.get("preflight_attempt", 0) + 1

    best_creative = state.get("best_creative")
    best_preflight = state.get("best_preflight")
    if best_preflight is None or result.predicted_engagement > best_preflight.predicted_engagement:
        best_creative, best_preflight = creative, result

    upsert_iteration(
        state["campaign_id"],
        state["user_id"],
        state["round_id"],
        copy_text=best_creative.copy_text,
        image_prompt=best_creative.image_prompt,
        preflight_score=best_preflight.predicted_engagement,
        preflight_passed=best_preflight.passed,
        preflight_attempt=attempt,
        image_style=best_creative.image_style,
        copy_tone=best_creative.copy_tone,
        arm_index=best_creative.arm_index,
        arm_explain=best_creative.arm_explain,
        # Shown at Gate 2: blocking issues left after the rewrites, and claims to review.
        guardrail_flags=best_creative.guardrails.model_dump(),
        # Kept so Gate 2 can repaint the picture with the same words (capability "ad_image").
        headline=best_creative.headline,
        cta=best_creative.cta,
        template=best_creative.template or None,
        ad_slots=best_creative.ad_slots,
        **_stored_image(state, best_creative.image_bytes, getattr(best_creative, "scene_bytes", None)),
    )

    return {
        "creative": best_creative,
        "preflight": best_preflight,
        "preflight_attempt": attempt,
        "best_creative": best_creative,
        "best_preflight": best_preflight,
    }


def route_after_preflight(state: CampaignState) -> str:
    if state["preflight"].passed or state["preflight_attempt"] >= MAX_PREFLIGHT_ATTEMPTS:
        return "gate_2"
    return "generate_creative"
