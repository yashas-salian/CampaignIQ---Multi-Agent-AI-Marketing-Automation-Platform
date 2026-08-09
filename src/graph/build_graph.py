import os

from langgraph.graph import END, START, StateGraph

from src.graph.nodes.audience import audience_node
from src.graph.nodes.creative import creative_node
from src.graph.nodes.distribution_bluesky import distribution_bluesky_node
from src.graph.nodes.distribution_email import distribution_email_node
from src.graph.nodes.distribution_reddit import distribution_reddit_node
from src.graph.nodes.feasibility import feasibility_node
from src.graph.nodes.finalize import finalize_node
from src.graph.nodes.human_gate import gate_1_node, gate_2_node
from src.graph.nodes.idea_intake import idea_intake_node
from src.graph.nodes.preflight import preflight_node, route_after_preflight
from src.graph.state import CampaignState


def route_after_gate_1(state: CampaignState) -> str:
    return END if state.get("rejected") else "generate_creative"


def route_after_gate_2(state: CampaignState) -> list[str]:
    if state.get("rejected"):
        return [END]
    # Reddit temporarily on hold (API access blocked by policy changes) — the
    # node/capability/CLI command all still exist, just excluded from the
    # default fan-out. Re-enable via ENABLE_REDDIT=true.
    channels = ["distribution_bluesky", "distribution_email"]
    if os.environ.get("ENABLE_REDDIT", "false").lower() == "true":
        channels.append("distribution_reddit")
    return channels


def build_graph(checkpointer=None):
    graph = StateGraph(CampaignState)
    graph.add_node("idea_intake", idea_intake_node)
    graph.add_node("score_feasibility", feasibility_node)
    graph.add_node("audience", audience_node)
    graph.add_node("gate_1", gate_1_node)
    graph.add_node("generate_creative", creative_node)
    graph.add_node("run_preflight", preflight_node)
    graph.add_node("gate_2", gate_2_node)
    graph.add_node("distribution_bluesky", distribution_bluesky_node)
    graph.add_node("distribution_reddit", distribution_reddit_node)
    graph.add_node("distribution_email", distribution_email_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "idea_intake")
    graph.add_edge("idea_intake", "score_feasibility")
    graph.add_edge("score_feasibility", "audience")
    graph.add_edge("audience", "gate_1")
    graph.add_conditional_edges(
        "gate_1", route_after_gate_1, {END: END, "generate_creative": "generate_creative"}
    )
    graph.add_edge("generate_creative", "run_preflight")
    graph.add_conditional_edges(
        "run_preflight",
        route_after_preflight,
        {"gate_2": "gate_2", "generate_creative": "generate_creative"},
    )
    graph.add_conditional_edges(
        "gate_2",
        route_after_gate_2,
        {
            END: END,
            "distribution_bluesky": "distribution_bluesky",
            "distribution_reddit": "distribution_reddit",
            "distribution_email": "distribution_email",
        },
    )
    graph.add_edge("distribution_bluesky", "finalize")
    graph.add_edge("distribution_reddit", "finalize")
    graph.add_edge("distribution_email", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
