from src.capabilities.email_engine import send_round
from src.graph.state import CampaignState


def distribution_email_node(state: CampaignState) -> CampaignState:
    """The round's email: everything happens in the email engine."""
    return send_round(state)
