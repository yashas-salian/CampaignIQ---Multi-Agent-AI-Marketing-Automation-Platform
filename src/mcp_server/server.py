"""M8: MarketingOS capabilities as an MCP server.

Wraps the same `capabilities/` functions the graph, the Tools page and CI use
(one implementation per capability, no drift), so Claude Desktop or any other
MCP client can call them directly:

  python -m src.mcp_server.server                 # stdio (Claude Desktop, Claude Code)
  python -m src.mcp_server.server --http 8765     # streamable HTTP for other clients

Configuration comes from the same .env as the rest of the app.
  MCP_USER_ID   optional Supabase user id. Resolves that user's BYOK/paid
                providers and unlocks the campaign tools, which only ever read
                that user's own campaigns. Unset: free tier, no campaign access.
  DRY_RUN       distribution tools only *describe* what they would send unless
                DRY_RUN=false (the app-wide default is true).
"""
import argparse
import base64
import contextlib
import os
import sys
import uuid
from pathlib import Path
from typing import Annotated, Literal

import anyio
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from pydantic import Field

# Explicit path: MCP clients launch the server from their own working directory.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

mcp = FastMCP(
    "marketingos",
    instructions=(
        "MarketingOS ad-campaign capabilities: classify an idea, score its market feasibility from live "
        "signals, generate customer personas, write ad creative (copy + image) chosen by a contextual "
        "bandit, pre-test it on a synthetic persona panel, distribute it, and read campaign results. "
        "A typical flow is classify_idea -> score_feasibility -> generate_personas -> generate_creative "
        "-> preflight_creative. Distribution tools are dry runs unless the server runs with DRY_RUN=false."
    ),
)

Language = Annotated[str, Field(description="Target-audience language code, e.g. en, es, fr, de, hi")]
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)
GENERATES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
SENDS = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)


def _user_id() -> str | None:
    return os.environ.get("MCP_USER_ID") or None


async def _run(fn, *args, **kwargs):
    """Run blocking capability code off the event loop. stdout is the stdio
    transport's wire, so any stray print from a library goes to stderr."""

    def call():
        with contextlib.redirect_stdout(sys.stderr):
            return fn(*args, **kwargs)

    return await anyio.to_thread.run_sync(call)


def _image(data: bytes) -> Image:
    return Image(data=data, format="jpeg" if data[:3] == b"\xff\xd8\xff" else "png")


def _owned_campaign(campaign_id: str) -> dict:
    from src.db.supabase_client import get_campaign

    user_id = _user_id()
    if not user_id:
        raise ValueError("Campaign tools need MCP_USER_ID set to your Supabase user id.")
    try:
        campaign = get_campaign(campaign_id)
    except Exception:
        campaign = None
    # Same answer for "missing" and "someone else's": the service-role key must
    # never leak whether another user's campaign exists.
    if not campaign or campaign.get("user_id") != user_id:
        raise ValueError(f"No campaign {campaign_id} for this user.")
    return campaign


# --- Idea + market -----------------------------------------------------------


@mcp.tool(annotations=READ_ONLY)
async def classify_idea(idea: Annotated[str, Field(description="Free-text ad-campaign or product idea")]) -> dict:
    """Normalize an idea and classify it into one of 12 product categories (the bandit's domain context).
    Uses the fine-tuned local model when installed, otherwise the LLM."""
    from src.capabilities.idea_intake import normalize_idea

    result = await _run(normalize_idea, idea, user_id=_user_id())
    return result.model_dump()


@mcp.tool(annotations=READ_ONLY)
async def score_feasibility(idea: str, target_language: Language = "en") -> dict:
    """Score market feasibility 0-100 from live signals (Google Trends interest, news volume, Bluesky/Mastodon
    community activity) with a rationale and the raw signal values. Takes ~10-30 s."""
    from src.capabilities.feasibility import score_feasibility as score

    result = await _run(score, idea, user_id=_user_id(), target_language=target_language)
    return result.model_dump()


@mcp.tool(annotations=GENERATES)
async def generate_personas(
    idea: str,
    n: Annotated[int, Field(ge=1, le=6, description="How many personas")] = 3,
    target_language: Language = "en",
) -> list[dict]:
    """Generate ideal-customer-profile personas for an idea, grounded in its feasibility signals.
    Pass one of the returned personas to generate_creative."""
    from src.capabilities.audience import generate_personas as personas
    from src.capabilities.feasibility import score_feasibility as score

    user_id = _user_id()
    feasibility = await _run(score, idea, user_id=user_id, target_language=target_language)
    result = await _run(personas, idea, feasibility, n=n, user_id=user_id, target_language=target_language)
    return [p.model_dump() for p in result]


# --- Creative ----------------------------------------------------------------


@mcp.tool(annotations=GENERATES)
async def generate_creative(
    idea: str,
    persona_name: str,
    demographics: str,
    psychographics: str,
    messaging_angle: str,
    channel_fit: str = "bluesky, email",
    age_bracket: Literal["18-24", "25-34", "35-44", "45-54", "55+"] = "25-34",
    income_tier: Literal["low", "mid", "high"] = "mid",
    domain_category: Annotated[str, Field(description="From classify_idea; 'other' if unknown")] = "other",
    target_language: Language = "en",
    revision_directive: Annotated[str | None, Field(description="Optional guidance from a previous round")] = None,
) -> list:
    """Write ad copy and generate a matching image for one persona. The image style and copy tone are picked
    by the LinUCB contextual bandit for this persona/domain, so results reflect what has performed best."""
    from src.capabilities.audience import Persona
    from src.capabilities.creative import generate_creative as creative
    from src.capabilities.idea_intake import DOMAIN_CATEGORIES
    from src.constants import active_channels

    persona = Persona(
        name=persona_name,
        demographics=demographics,
        psychographics=psychographics,
        channel_fit=channel_fit,
        messaging_angle=messaging_angle,
        age_bracket=age_bracket,
        income_tier=income_tier,
    )
    result = await _run(
        creative,
        idea,
        persona,
        domain_category=domain_category if domain_category in DOMAIN_CATEGORIES else "other",
        active_channels=active_channels(),
        user_id=_user_id(),
        revision_directive=revision_directive,
        target_language=target_language,
    )
    summary = {
        "copy_text": result.copy_text,
        "image_prompt": result.image_prompt,
        "image_style": result.image_style,
        "copy_tone": result.copy_tone,
        "bandit_arm": result.arm_index,
        "brand_safety": result.guardrails.model_dump(),
    }
    return [summary, _image(result.image_bytes)]


@mcp.tool(annotations=GENERATES)
async def generate_image(prompt: Annotated[str, Field(description="Visual description, in English")]) -> Image:
    """Generate one image from a prompt with the user's image provider (free tier: Pollinations)."""
    from src.providers.registry import get_image_generator

    data = await _run(lambda: get_image_generator(_user_id()).generate_image(prompt))
    return _image(data)


@mcp.tool(annotations=READ_ONLY)
async def preflight_creative(
    copy_text: str,
    image_prompt: str,
    personas: Annotated[list[dict], Field(description="Personas as returned by generate_personas")],
    target_language: Language = "en",
) -> dict:
    """Pre-test creative on a synthetic panel of the given personas before spending any reach:
    predicted engagement 0-100, pass/fail (threshold 50), and the panel's honest feedback."""
    from src.capabilities.audience import Persona
    from src.capabilities.creative import Creative
    from src.capabilities.preflight import score_preflight

    creative = Creative(
        copy_text=copy_text, image_prompt=image_prompt, image_bytes=b"", image_style="", copy_tone="", arm_index=-1
    )
    panel = [Persona(**p) for p in personas]
    result = await _run(score_preflight, creative, panel, user_id=_user_id(), target_language=target_language)
    return result.model_dump()


# --- Distribution (dry run unless DRY_RUN=false) ------------------------------


def _send_ids(campaign_id: str | None, round_id: int) -> tuple[str, int]:
    # The dedup store makes a (campaign, round, channel) send idempotent; ad-hoc
    # calls get a fresh id so they never collide with a real campaign's rounds.
    return campaign_id or f"mcp-{uuid.uuid4()}", round_id


@mcp.tool(annotations=SENDS)
async def post_bluesky(
    copy_text: Annotated[str, Field(max_length=300)],
    image_base64: Annotated[str | None, Field(description="Optional image to attach (base64)")] = None,
    campaign_id: Annotated[str | None, Field(description="Campaign to attribute the post to (dedups re-sends)")] = None,
    round_id: int = 1,
) -> str:
    """Post ad copy (and optional image) to Bluesky. A dry run that only describes the post unless the server
    runs with DRY_RUN=false. Sending the same campaign/round twice is skipped."""
    from src.capabilities.distribution import post_bluesky as post

    cid, rid = _send_ids(campaign_id, round_id)
    image = base64.b64decode(image_base64) if image_base64 else None
    return await _run(post, cid, rid, copy_text, image)


@mcp.tool(annotations=SENDS)
async def send_campaign_email(
    to: Annotated[list[str], Field(min_length=1, max_length=50)],
    subject: str,
    html: str,
    cta_url: Annotated[str | None, Field(description="Call-to-action link; click-tracked when configured")] = None,
    campaign_id: str | None = None,
    round_id: int = 1,
) -> str:
    """Email the campaign creative via Resend. A dry run unless the server runs with DRY_RUN=false.
    Sending the same campaign/round twice is skipped."""
    from src.capabilities.distribution import send_campaign_email as send

    cid, rid = _send_ids(campaign_id, round_id)
    return await _run(send, cid, rid, to, subject, html, cta_url=cta_url)


# --- Campaigns (MCP_USER_ID's own, read-only) ---------------------------------


@mcp.tool(annotations=READ_ONLY)
async def list_campaigns(limit: Annotated[int, Field(ge=1, le=50)] = 10) -> list[dict]:
    """List your most recent campaigns (id, idea, category, status, feasibility). Needs MCP_USER_ID."""
    from src.db.supabase_client import get_client

    user_id = _user_id()
    if not user_id:
        raise ValueError("Campaign tools need MCP_USER_ID set to your Supabase user id.")

    def query():
        return (
            get_client()
            .table("campaigns")
            .select("id,idea,domain_category,status,feasibility_score,created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    return await _run(query)


@mcp.tool(annotations=READ_ONLY)
async def campaign_summary(campaign_id: str) -> dict:
    """Results of one of your campaigns: rounds run, reward per round, the winning round and total
    engagement per channel. Needs MCP_USER_ID."""
    from src.capabilities.feedback_correction import build_campaign_summary

    campaign = await _run(_owned_campaign, campaign_id)
    summary = await _run(build_campaign_summary, campaign_id)
    return {"idea": campaign["idea"], "status": campaign["status"], **summary}


def _preload() -> None:
    """Import native-extension libraries on the main thread before serving.

    On Windows, the first import of a DLL-backed module (numpy, llama.cpp,
    torch) from a worker thread deadlocks while the stdio transport has a thread
    blocked reading stdin -- tools run in worker threads, so classify_idea hung
    forever. Importing them here, before the transport starts, avoids it (and
    makes the first tool call fast)."""
    import importlib

    modules = ["numpy", "pandas", "PIL.Image", "pytrends.request", "atproto", "src.tools.bandit"]
    if _user_id():
        modules.append("sentence_transformers")  # feasibility's own-history retrieval
    for name in modules:
        importlib.import_module(name)
    with contextlib.redirect_stdout(sys.stderr):
        from src.providers.free.local_domain_classifier import available

        available()  # loads the fine-tuned GGUF if present (llama.cpp); False -> LLM fallback


def main() -> None:
    parser = argparse.ArgumentParser(description="MarketingOS MCP server")
    parser.add_argument("--http", type=int, metavar="PORT", help="serve streamable HTTP on 127.0.0.1:PORT instead of stdio")
    args = parser.parse_args()
    _preload()
    if args.http:
        mcp.settings.host, mcp.settings.port = "127.0.0.1", args.http
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
