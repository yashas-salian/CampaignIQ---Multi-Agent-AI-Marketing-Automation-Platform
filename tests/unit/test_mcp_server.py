import base64
import json

import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from src.capabilities.idea_intake import NormalizedIdea
from src.mcp_server import server

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16


def call(tool: str, args: dict | None = None):
    async def run():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return await client.call_tool(tool, args or {})

    return anyio.run(run)


def text(result) -> str:
    return " ".join(c.text for c in result.content if c.type == "text")


def test_lists_every_tool_with_safety_annotations():
    async def run():
        async with create_connected_server_and_client_session(server.mcp._mcp_server) as client:
            return (await client.list_tools()).tools

    tools = {t.name: t for t in anyio.run(run)}
    assert set(tools) == {
        "classify_idea", "score_feasibility", "generate_personas", "generate_creative", "generate_image",
        "preflight_creative", "post_bluesky", "send_campaign_email", "list_campaigns", "campaign_summary",
        "evaluate_decision", "crash_test_ad", "measure_impact", "assess_creative_fatigue",
    }
    assert tools["classify_idea"].annotations.readOnlyHint is True
    assert tools["evaluate_decision"].annotations.readOnlyHint is True
    assert tools["measure_impact"].annotations.readOnlyHint is True
    assert tools["assess_creative_fatigue"].annotations.readOnlyHint is True
    assert tools["post_bluesky"].annotations.destructiveHint is True
    assert tools["send_campaign_email"].annotations.destructiveHint is True


def test_classify_idea_wraps_the_capability(monkeypatch):
    seen = {}

    def fake(idea, user_id=None):
        seen["user_id"] = user_id
        return NormalizedIdea(idea=idea, domain_category="education")

    monkeypatch.setattr("src.capabilities.idea_intake.normalize_idea", fake)
    monkeypatch.setenv("MCP_USER_ID", "user-1")
    result = call("classify_idea", {"idea": "A tutoring app"})
    assert not result.isError
    assert json.loads(text(result)) == {"idea": "A tutoring app", "domain_category": "education"}
    assert seen["user_id"] == "user-1"


def test_stray_prints_never_reach_the_protocol_stream(monkeypatch):
    def noisy(idea, user_id=None):
        print("library chatter on stdout")
        return NormalizedIdea(idea=idea, domain_category="other")

    monkeypatch.setattr("src.capabilities.idea_intake.normalize_idea", noisy)
    assert not call("classify_idea", {"idea": "x"}).isError


def test_generate_image_returns_image_content(monkeypatch):
    class Provider:
        def generate_image(self, prompt):
            return PNG

    monkeypatch.setattr("src.providers.registry.get_image_generator", lambda user_id=None: Provider())
    result = call("generate_image", {"prompt": "spice jars"})
    image = next(c for c in result.content if c.type == "image")
    assert image.mimeType == "image/png" and base64.b64decode(image.data) == PNG


def test_post_bluesky_is_a_dry_run_with_a_fresh_campaign_id(monkeypatch):
    monkeypatch.setattr("src.capabilities.distribution.post_to_bluesky", lambda *a, **k: pytest.fail("real post"))
    first, second = call("post_bluesky", {"copy_text": "Hello"}), call("post_bluesky", {"copy_text": "Hello"})
    assert text(first).startswith("DRY_RUN") and text(second).startswith("DRY_RUN")  # ad-hoc calls never collide


def test_campaign_tools_need_a_user():
    result = call("list_campaigns")
    assert result.isError and "MCP_USER_ID" in text(result)


def test_another_users_campaign_looks_missing(monkeypatch):
    monkeypatch.setenv("MCP_USER_ID", "me")
    campaigns = {"mine": {"user_id": "me", "idea": "i", "status": "completed"}, "theirs": {"user_id": "them"}}
    monkeypatch.setattr("src.db.supabase_client.get_campaign", lambda cid: campaigns.get(cid))
    monkeypatch.setattr(
        "src.capabilities.feedback_correction.build_campaign_summary", lambda cid: {"total_rounds": 2}
    )
    assert json.loads(text(call("campaign_summary", {"campaign_id": "mine"})))["total_rounds"] == 2
    theirs, missing = call("campaign_summary", {"campaign_id": "theirs"}), call("campaign_summary", {"campaign_id": "nope"})
    assert theirs.isError and missing.isError
    assert text(theirs).replace("theirs", "<id>") == text(missing).replace("nope", "<id>")
