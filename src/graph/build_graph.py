from langgraph.graph import END, START, StateGraph

from src.graph.nodes.audience import audience_node
from src.graph.nodes.creative import creative_node
from src.graph.nodes.distribution_bluesky import distribution_bluesky_node
from src.graph.nodes.distribution_email import distribution_email_node
from src.graph.nodes.distribution_reddit import distribution_reddit_node
from src.graph.nodes.feasibility import feasibility_node
from src.graph.nodes.idea_intake import idea_intake_node
from src.graph.state import CampaignState


def build_graph():
    graph = StateGraph(CampaignState)
    graph.add_node("idea_intake", idea_intake_node)
    graph.add_node("score_feasibility", feasibility_node)
    graph.add_node("audience", audience_node)
    graph.add_node("generate_creative", creative_node)
    graph.add_node("distribution_bluesky", distribution_bluesky_node)
    graph.add_node("distribution_reddit", distribution_reddit_node)
    graph.add_node("distribution_email", distribution_email_node)

    graph.add_edge(START, "idea_intake")
    graph.add_edge("idea_intake", "score_feasibility")
    graph.add_edge("score_feasibility", "audience")
    graph.add_edge("audience", "generate_creative")
    graph.add_edge("generate_creative", "distribution_bluesky")
    graph.add_edge("generate_creative", "distribution_reddit")
    graph.add_edge("generate_creative", "distribution_email")
    graph.add_edge("distribution_bluesky", END)
    graph.add_edge("distribution_reddit", END)
    graph.add_edge("distribution_email", END)

    return graph.compile()


if __name__ == "__main__":
    import os
    import sys

    from dotenv import load_dotenv

    load_dotenv()

    idea = sys.argv[1] if len(sys.argv) > 1 else "A subscription box for artisanal hot sauce"
    email_to = sys.argv[2].split(",") if len(sys.argv) > 2 else [os.environ["RESEND_TEST_TO_EMAIL"]]

    app = build_graph()
    result = app.invoke({"idea": idea, "email_to": email_to})

    print(f"Feasibility score: {result['feasibility'].score}")
    print(f"Rationale: {result['feasibility'].rationale}")
    print(f"Personas generated: {len(result['personas'])}")
    print(f"Creative copy: {result['creative'].copy_text}")
    print(f"Bluesky: {result['bluesky_post_uri']}")
    print(f"Reddit: {result['reddit_post_url']}")
    print(f"Email id: {result['email_id']}")
