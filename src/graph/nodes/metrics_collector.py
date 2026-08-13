from src.capabilities.metrics import collect_metrics
from src.graph.state import CampaignState


def metrics_collector_node(state: CampaignState) -> CampaignState:
    result = collect_metrics(state["campaign_id"], state["user_id"], state["round_id"], email_to=state.get("email_to"))
    return {"metrics_result": result}
