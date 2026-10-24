import argparse
import base64
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.db.supabase_client import get_client
from src.usage import budget_exhausted, personal_org, use_org


def _run_feasibility(params: dict, user_id: str) -> dict:
    from src.capabilities.feasibility import score_feasibility

    result = score_feasibility(params["idea"], user_id=user_id, target_language=params.get("target_language", "en"))
    return result.model_dump()


def _run_personas(params: dict, user_id: str) -> list[dict]:
    from src.capabilities.audience import generate_personas
    from src.capabilities.feasibility import score_feasibility

    target_language = params.get("target_language", "en")
    feasibility = score_feasibility(params["idea"], user_id=user_id, target_language=target_language)
    personas = generate_personas(
        params["idea"], feasibility, n=params.get("n", 3), user_id=user_id, target_language=target_language
    )
    return [p.model_dump() for p in personas]


def _run_creative(params: dict, user_id: str) -> dict:
    from src.capabilities.creative import Persona, generate_creative
    from src.constants import active_channels

    persona_params = {"age_bracket": "25-34", "income_tier": "mid", **params["persona"]}
    persona = Persona(**persona_params)
    result = generate_creative(
        params["idea"], persona, domain_category=params.get("domain_category", "other"),
        active_channels=active_channels(), user_id=user_id, target_language=params.get("target_language", "en"),
    )
    return {
        "copy_text": result.copy_text,
        "image_prompt": result.image_prompt,
        "image_base64": base64.b64encode(result.image_bytes).decode(),
    }


def _run_image(params: dict, user_id: str) -> dict:
    from src.providers.registry import get_image_generator

    data = get_image_generator(user_id).generate_image(params["prompt"])
    return {"image_base64": base64.b64encode(data).decode()}


# New pictures per round at Gate 2: each one is a paid image call on some tiers.
MAX_REPAINTS = 5
APPROVER_ROLES = ("owner", "admin", "approver")  # role_can(..., 'approve') in the organizations migration


def _run_ad_image(params: dict, user_id: str) -> dict:
    """Gate 2's "New picture": repaint a round's ad with the same prompt,
    words, layout and brand, and replace the stored image (the gate sends the
    stored one once image_version > 0, see human_gate.gate_2_node)."""
    from src.capabilities.brand import brand_kit_for_campaign, brand_logo
    from src.capabilities.creative import AD_VISUAL_SUFFIX
    from src.db.supabase_client import upload_ad_image
    from src.providers.registry import get_image_generator
    from src.tools.ad_composer import compose_ad

    campaign_id, round_number = str(params["campaign_id"]), int(params["round"])
    client = get_client()
    campaign = client.table("campaigns").select("org_id,status,current_round").eq("id", campaign_id).maybe_single().execute()
    campaign = campaign.data if campaign else None
    if not campaign:
        raise ValueError("campaign not found")
    # The worker runs as the service role, so check the caller's right here.
    member = (
        client.table("memberships").select("role").eq("org_id", campaign["org_id"]).eq("user_id", user_id)
        .maybe_single().execute()
    )
    if not member or not member.data or member.data["role"] not in APPROVER_ROLES:
        raise PermissionError("only approvers can repaint an ad")
    if campaign["status"] != "awaiting_gate_2" or campaign.get("current_round") != round_number:
        raise ValueError("a new picture can only be made while this round waits at Gate 2")
    iteration = (
        client.table("iterations").select("image_prompt,headline,cta,image_style,image_version")
        .eq("campaign_id", campaign_id).eq("round_number", round_number).maybe_single().execute()
    )
    iteration = iteration.data if iteration else None
    if not iteration or not iteration.get("image_prompt"):
        raise ValueError("this round has no image to repaint")
    version = int(iteration.get("image_version") or 0)
    if version >= MAX_REPAINTS:
        raise ValueError(f"at most {MAX_REPAINTS} new pictures per round")

    kit = brand_kit_for_campaign(campaign_id)
    picture = get_image_generator(user_id).generate_image(iteration["image_prompt"] + AD_VISUAL_SUFFIX)
    ad = compose_ad(
        picture, iteration.get("headline") or "", iteration.get("cta") or "",
        brand_color=kit.brand_color if kit else None, style=iteration.get("image_style"), logo_bytes=brand_logo(kit),
    )
    path = upload_ad_image(campaign_id, round_number, ad)
    client.table("iterations").update({"image_path": path, "image_version": version + 1}).eq(
        "campaign_id", campaign_id
    ).eq("round_number", round_number).execute()
    return {"campaign_id": campaign_id, "round": round_number, "image_version": version + 1}


CAPABILITY_DISPATCH = {
    "feasibility": _run_feasibility,
    "personas": _run_personas,
    "creative": _run_creative,
    "image": _run_image,
    "ad_image": _run_ad_image,
}


def main() -> None:
    load_dotenv()
    from src.observability import init

    init("tools-run")
    parser = argparse.ArgumentParser(description="GitHub Actions entrypoint for a single Tools-page capability run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--params", default="{}")
    args = parser.parse_args()

    client = get_client()
    params = json.loads(args.params)

    # Tools runs count against the user's personal organisation.
    org_id = personal_org(args.user_id)
    use_org(org_id)
    blocked = budget_exhausted(org_id)
    if blocked:
        client.table("capability_runs").update({"status": "failed", "error": blocked}).eq("id", args.run_id).execute()
        return

    client.table("capability_runs").update({"status": "running"}).eq("id", args.run_id).execute()

    handler = CAPABILITY_DISPATCH.get(args.capability)
    if not handler:
        client.table("capability_runs").update(
            {"status": "failed", "error": f"Unknown capability: {args.capability}"}
        ).eq("id", args.run_id).execute()
        sys.exit(1)

    try:
        result = handler(params, args.user_id)
        client.table("capability_runs").update(
            {
                "status": "completed",
                "result": result,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", args.run_id).execute()
    except Exception as exc:
        client.table("capability_runs").update({"status": "failed", "error": str(exc)}).eq("id", args.run_id).execute()
        raise


if __name__ == "__main__":
    main()
