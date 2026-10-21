import os

from langgraph.graph import END, START, StateGraph

from src.graph.nodes.audience import audience_node
from src.graph.nodes.creative import creative_node
from src.graph.nodes.distribution_bluesky import distribution_bluesky_node
from src.graph.nodes.distribution_email import distribution_email_node
from src.graph.nodes.distribution_reddit import distribution_reddit_node
from src.graph.nodes.feasibility import feasibility_node
from src.graph.nodes.feedback_correction import feedback_correction_node, route_after_feedback
from src.graph.nodes.finalize import finalize_node
from src.graph.nodes.human_gate import gate_1_node, gate_2_node
from src.graph.nodes.idea_intake import idea_intake_node
from src.graph.nodes.metrics_collector import metrics_collector_node
from src.graph.nodes.metrics_wait import metrics_wait_node
from src.graph.nodes.novelty_check import novelty_check_node, route_after_novelty_check
from src.graph.nodes.preflight import preflight_node, route_after_preflight
from src.graph.nodes.variant_b import generate_variant_b_node
from src.graph.state import CampaignState
from src.observability import traced_node


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
    graph.add_node("idea_intake", traced_node("idea_intake", idea_intake_node))
    graph.add_node("score_feasibility", traced_node("score_feasibility", feasibility_node))
    graph.add_node("audience", traced_node("audience", audience_node))
    graph.add_node("gate_1", traced_node("gate_1", gate_1_node))
    graph.add_node("generate_creative", traced_node("generate_creative", creative_node))
    graph.add_node("novelty_check", traced_node("novelty_check", novelty_check_node))
    graph.add_node("run_preflight", traced_node("run_preflight", preflight_node))
    graph.add_node("generate_variant_b", traced_node("generate_variant_b", generate_variant_b_node))
    graph.add_node("gate_2", traced_node("gate_2", gate_2_node))
    graph.add_node("distribution_bluesky", traced_node("distribution_bluesky", distribution_bluesky_node))
    graph.add_node("distribution_reddit", traced_node("distribution_reddit", distribution_reddit_node))
    graph.add_node("distribution_email", traced_node("distribution_email", distribution_email_node))
    graph.add_node("wait_for_metrics", traced_node("wait_for_metrics", metrics_wait_node))
    graph.add_node("collect_metrics", traced_node("collect_metrics", metrics_collector_node))
    graph.add_node("feedback_correction", traced_node("feedback_correction", feedback_correction_node))
    graph.add_node("finalize", traced_node("finalize", finalize_node))

    graph.add_edge(START, "idea_intake")
    graph.add_edge("idea_intake", "score_feasibility")
    graph.add_edge("score_feasibility", "audience")
    graph.add_edge("audience", "gate_1")
    graph.add_conditional_edges("gate_1", route_after_gate_1, {END: END, "generate_creative": "generate_creative"})
    graph.add_edge("generate_creative", "novelty_check")
    graph.add_conditional_edges(
        "novelty_check",
        route_after_novelty_check,
        {"run_preflight": "run_preflight", "generate_creative": "generate_creative"},
    )
    graph.add_conditional_edges(
        "run_preflight",
        route_after_preflight,
        {"gate_2": "generate_variant_b", "generate_creative": "generate_creative"},
    )
    graph.add_edge("generate_variant_b", "gate_2")
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
    graph.add_edge("distribution_bluesky", "wait_for_metrics")
    graph.add_edge("distribution_reddit", "wait_for_metrics")
    graph.add_edge("distribution_email", "wait_for_metrics")
    graph.add_edge("wait_for_metrics", "collect_metrics")
    graph.add_edge("collect_metrics", "feedback_correction")
    graph.add_conditional_edges(
        "feedback_correction",
        route_after_feedback,
        {"generate_creative": "generate_creative", "finalize": "finalize"},
    )
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=checkpointer)
