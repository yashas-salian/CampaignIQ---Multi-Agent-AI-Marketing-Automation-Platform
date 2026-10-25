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
    """The Tools page's ad image: the user's product photo cut out and set
    into a template (the one they picked, or the best fit for the
    description), with words written from the description."""
    from src.capabilities.brand import brand_kit_for_org
    from src.capabilities.creative import Persona, generate_creative
    from src.capabilities.product import PRODUCT_PHOTOS_BUCKET
    from src.constants import active_channels
    from src.db.supabase_client import download_object
    from src.tools.ad_templates import TEMPLATES
    from src.tools.product_cutout import cutout

    path = str(params.get("product_image_path") or "")
    if not path:
        raise ValueError("add a photo of your product to make an ad image")
    # The worker reads storage as the service role: only the caller's own photos.
    if not path.startswith(f"{user_id}/") or ".." in path:
        raise PermissionError("that product photo isn't yours")
    template = params.get("template") if params.get("template") in TEMPLATES else None
    persona = Persona(
        name="Typical customer", demographics="", psychographics="", channel_fit="bluesky",
        messaging_angle="", age_bracket="25-34", income_tier="mid",
    )
    result = generate_creative(
        params["prompt"], persona, domain_category=params.get("domain_category", "other"), active_channels=active_channels(),
        user_id=user_id, target_language=params.get("target_language", "en"), brand=brand_kit_for_org(personal_org(user_id)),
        product_cutout=cutout(download_object(PRODUCT_PHOTOS_BUCKET, path)), tagline=str(params.get("tagline") or "").strip()[:80],
        template=template, arm=(-1, TEMPLATES[template].family, "direct_factual") if template else None,
    )
    return {
        "image_base64": base64.b64encode(result.image_bytes).decode(),
        "mime": "image/jpeg",
        "template": result.template,
        "headline": result.headline,
        "copy_text": result.copy_text,
    }


def _run_decision(params: dict, user_id: str) -> dict:
    """Should we advertise this at all? Research, personas, then the decision
    engine (src/capabilities/decision.py), without starting a campaign."""
    from src.capabilities.audience import generate_personas
    from src.capabilities.brand import brand_kit_for_org
    from src.capabilities.decision import evaluate, inputs_from
    from src.capabilities.feasibility import score_feasibility
    from src.capabilities.idea_intake import normalize_idea

    idea = str(params["idea"]).strip()
    language = params.get("target_language", "en")
    domain = params.get("domain_category") or normalize_idea(idea, user_id=user_id).domain_category
    feasibility = score_feasibility(idea, user_id=user_id, target_language=language)
    personas = generate_personas(idea, feasibility, n=3, user_id=user_id, target_language=language)
    org_id = personal_org(user_id) if user_id else None  # the MCP server may run without a user
    kit = brand_kit_for_org(org_id)
    inputs = inputs_from(
        idea, feasibility, personas, domain_category=domain, target_language=language, org_id=org_id,
        cta_url=(params.get("cta_url") or None), banned_terms=kit.forbidden_words if kit else (),
    )
    return {
        **evaluate(inputs).model_dump(),
        "feasibility_score": feasibility.score,
        "feasibility_rationale": feasibility.rationale,
        "domain_category": domain,
    }


# New pictures per round at Gate 2: each one is a paid image call on some tiers.
MAX_REPAINTS = 5
APPROVER_ROLES = ("owner", "admin", "approver")  # role_can(..., 'approve') in the organizations migration


def _run_ad_image(params: dict, user_id: str) -> dict:
    """Gate 2's "New picture": repaint a round's ad with the same prompt,
    words, layout and brand, and replace the stored image (the gate sends the
    stored one once image_version > 0, see human_gate.gate_2_node)."""
    from src.capabilities.brand import brand_kit_for_campaign, brand_logo
    from src.capabilities.creative import AD_VISUAL_SUFFIX, SCENE_SUFFIX
    from src.capabilities.product import product_for_campaign
    from src.db.supabase_client import upload_ad_image
    from src.providers.registry import get_image_generator
    from src.tools.ad_composer import compose_ad
    from src.tools.ad_templates import TEMPLATES, compose_product_ad

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
        client.table("iterations").select("image_prompt,headline,cta,image_style,image_version,template,ad_slots")
        .eq("campaign_id", campaign_id).eq("round_number", round_number).maybe_single().execute()
    )
    iteration = iteration.data if iteration else None
    if not iteration or not iteration.get("image_prompt"):
        raise ValueError("this round has no image to repaint")
    version = int(iteration.get("image_version") or 0)
    if version >= MAX_REPAINTS:
        raise ValueError(f"at most {MAX_REPAINTS} new pictures per round")

    kit = brand_kit_for_campaign(campaign_id)
    product = product_for_campaign(campaign_id) if iteration.get("template") else None
    if product and product.cutout:
        # Product-first ad: same template and words. A painted background gets
        # a new painting; a drawn one gets its next colour/arrangement variant.
        slots = iteration.get("ad_slots") or {}
        template = TEMPLATES.get(iteration["template"])
        scene = None
        if template and template.scene:
            scene = get_image_generator(user_id).generate_image((slots.get("scene") or template.scene) + SCENE_SUFFIX)
            upload_ad_image(campaign_id, round_number, scene, variant="scene")  # kept for redrawing with new words
        ad = compose_product_ad(
            product.cutout, iteration["template"], {**slots, "headline": iteration.get("headline"), "cta": iteration.get("cta")},
            brand_color=kit.brand_color if kit else None, logo_bytes=brand_logo(kit), scene_bytes=scene, seed=version + 1,
        )
    else:
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


def _gate_2_round(params: dict, user_id: str, action: str) -> tuple[str, int, dict]:
    """(campaign_id, round, campaign row) for an approver acting on a round
    that's waiting at Gate 2; raises otherwise. The worker runs as the service
    role, so the caller's right is checked here."""
    campaign_id, round_number = str(params["campaign_id"]), int(params["round"])
    client = get_client()
    campaign = client.table("campaigns").select("org_id,status,current_round").eq("id", campaign_id).maybe_single().execute()
    campaign = campaign.data if campaign else None
    if not campaign:
        raise ValueError("campaign not found")
    member = (
        client.table("memberships").select("role").eq("org_id", campaign["org_id"]).eq("user_id", user_id)
        .maybe_single().execute()
    )
    if not member or not member.data or member.data["role"] not in APPROVER_ROLES:
        raise PermissionError(f"only approvers can {action}")
    if campaign["status"] != "awaiting_gate_2" or campaign.get("current_round") != round_number:
        raise ValueError(f"you can only {action} while this round waits at Gate 2")
    return campaign_id, round_number, campaign


def _run_crash_test(params: dict, user_id: str) -> dict:
    """Crash-test an ad. With campaign_id + round: re-run on the copy now at
    Gate 2 (after edits), stored with the campaign. Otherwise (Tools page,
    MCP, API): test the given idea and ad text without a campaign."""
    from src.capabilities.crash_test import AdText, run_crash_test, run_for_round
    from src.capabilities.decision import check_destination

    if params.get("campaign_id"):
        campaign_id, round_number, _ = _gate_2_round(params, user_id, "re-run the crash test")
        it = (get_client().table("iterations").select("copy_text,headline,cta,image_prompt")
              .eq("campaign_id", campaign_id).eq("round_number", round_number).maybe_single().execute())
        it = (it.data if it else None) or {}
        if not it.get("copy_text"):
            raise ValueError("this round has no ad yet")
        ad = AdText(body=it["copy_text"], headline=it.get("headline") or "", cta=it.get("cta") or "", visual=it.get("image_prompt") or "")
        report = run_for_round(campaign_id, round_number, user_id=user_id, ad=ad, trigger="rerun")
        return {"campaign_id": campaign_id, "round": round_number, "risk": report.risk, "revised_risk": report.revised_risk}
    ad = AdText(body=str(params.get("copy") or "").strip(), headline=str(params.get("headline") or "").strip(),
                cta=str(params.get("cta") or "").strip(), visual=str(params.get("visual") or "").strip())
    if not ad.body:
        raise ValueError("paste the ad's text to crash-test it")
    cta_url = params.get("cta_url") or None
    return run_crash_test(
        ad, idea=str(params.get("idea") or ad.body), tagline=str(params.get("tagline") or ""),
        domain_category=params.get("domain_category") or "other", cta_url=cta_url, destination=check_destination(cta_url),
        language=params.get("target_language", "en"), user_id=user_id,
    ).model_dump()


def _run_apply_revision(params: dict, user_id: str) -> dict:
    """Gate 2: use the crash test's revised version. The copy goes in through
    the version history (like an approver's edit); a changed headline or button
    redraws the ad from its template and stored background, with no new image
    generation. The crash test is marked applied, so Gate 2's risk is the revision's."""
    from src.capabilities.brand import brand_kit_for_campaign, brand_logo
    from src.capabilities.product import product_for_campaign
    from src.db.supabase_client import AD_IMAGES_BUCKET, download_object, upload_ad_image
    from src.tools.ad_templates import TEMPLATES, compose_product_ad

    campaign_id, round_number, campaign = _gate_2_round(params, user_id, "apply a revision")
    client = get_client()
    test = (client.table("crash_tests").select("id,report,applied_at,round_number,campaign_id")
            .eq("id", str(params["crash_test_id"])).maybe_single().execute())
    test = test.data if test else None
    if not test or test["campaign_id"] != campaign_id or test["round_number"] != round_number:
        raise ValueError("crash test not found for this round")
    revised = (test["report"] or {}).get("revised")
    if not revised:
        raise ValueError("this crash test has no revised version")
    if test.get("applied_at"):
        raise ValueError("this revision is already applied")
    it = (client.table("iterations").select("copy_text,headline,cta,template,ad_slots,image_version")
          .eq("campaign_id", campaign_id).eq("round_number", round_number).maybe_single().execute())
    it = (it.data if it else None) or {}

    # The copy, with the version history Gate 2 shows (the AI's original kept as version 1).
    has_history = (client.table("copy_revisions").select("id").eq("campaign_id", campaign_id)
                   .eq("round_number", round_number).eq("variant", "a").limit(1).execute().data)
    if not has_history and it.get("copy_text"):
        client.table("copy_revisions").insert({"campaign_id": campaign_id, "round_number": round_number, "variant": "a",
                                               "copy_text": it["copy_text"], "edited_by": None}).execute()
    client.table("copy_revisions").insert({"campaign_id": campaign_id, "round_number": round_number, "variant": "a",
                                           "copy_text": revised["body"], "edited_by": user_id}).execute()
    update = {"copy_text": revised["body"]}
    redrawn = False
    words_changed = (revised.get("headline") or "") != (it.get("headline") or "") or (revised.get("cta") or "") != (it.get("cta") or "")
    template = TEMPLATES.get(it.get("template") or "")
    if words_changed and template:
        product = product_for_campaign(campaign_id)
        scene = None
        if template.scene:
            try:
                scene = download_object(AD_IMAGES_BUCKET, f"{campaign_id}/round-{round_number}-scene.jpg")
            except Exception:
                scene = None  # older ads: the template draws its own background
        if product.cutout:
            kit = brand_kit_for_campaign(campaign_id)
            version = int(it.get("image_version") or 0)
            ad = compose_product_ad(
                product.cutout, template.id, {**(it.get("ad_slots") or {}), "headline": revised.get("headline"), "cta": revised.get("cta")},
                brand_color=kit.brand_color if kit else None, logo_bytes=brand_logo(kit), scene_bytes=scene, seed=version,
            )
            update |= {"image_path": upload_ad_image(campaign_id, round_number, ad), "image_version": version + 1,
                       "headline": revised.get("headline"), "cta": revised.get("cta")}
            redrawn = True
    client.table("iterations").update(update).eq("campaign_id", campaign_id).eq("round_number", round_number).execute()
    client.table("crash_tests").update({"applied_at": datetime.now(timezone.utc).isoformat(), "applied_by": user_id}).eq(
        "id", test["id"]).execute()
    return {"campaign_id": campaign_id, "round": round_number, "copy_applied": True, "image_redrawn": redrawn,
            "words_kept": words_changed and not redrawn}


def _run_circuit_breaker(params: dict, user_id: str) -> dict:
    """Evaluate a campaign's live conditions now (API: circuit-breaker/evaluate).
    Anyone who can view the campaign may ask; holds are placed as usual."""
    from src.capabilities.circuit_breaker import evaluate_campaign

    campaign_id = str(params["campaign_id"])
    client = get_client()
    campaign = client.table("campaigns").select("org_id").eq("id", campaign_id).maybe_single().execute()
    campaign = campaign.data if campaign else None
    if not campaign:
        raise ValueError("campaign not found")
    member = (client.table("memberships").select("role").eq("org_id", campaign["org_id"]).eq("user_id", user_id)
              .maybe_single().execute())
    if not member or not member.data:
        raise PermissionError("not a member of this campaign's organisation")
    signals = evaluate_campaign(campaign_id)
    holds = (client.table("campaign_holds").select("id,trigger,severity,status,detail,created_at")
             .eq("campaign_id", campaign_id).eq("status", "active").execute().data or [])
    return {"campaign_id": campaign_id, "signals": [s.__dict__ for s in signals], "active_holds": holds,
            "paused": any(h["severity"] == "critical" for h in holds)}


def _run_competitor_scan(params: dict, user_id: str) -> dict:
    """Fetch a competitor's approved sources now ("Scan now"). Owners, admins and
    marketers of its organisation only; robots.txt and the rest still apply."""
    from src.capabilities.competitors import scan_competitor

    client = get_client()
    found = client.table("competitors").select("*").eq("id", str(params["competitor_id"])).maybe_single().execute()
    competitor = found.data if found else None
    if not competitor:
        raise ValueError("competitor not found")
    member = (client.table("memberships").select("role").eq("org_id", competitor["org_id"]).eq("user_id", user_id)
              .maybe_single().execute())
    if not member or not member.data or member.data["role"] not in ("owner", "admin", "marketer"):
        raise PermissionError("only owners, admins and marketers can scan competitors")
    return scan_competitor(competitor, force=True, forecasts=[])


CAPABILITY_DISPATCH = {
    "feasibility": _run_feasibility,
    "personas": _run_personas,
    "creative": _run_creative,
    "image": _run_image,
    "ad_image": _run_ad_image,
    "decision": _run_decision,
    "crash_test": _run_crash_test,
    "apply_revision": _run_apply_revision,
    "circuit_breaker": _run_circuit_breaker,
    "competitor_scan": _run_competitor_scan,
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
