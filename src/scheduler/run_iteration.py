import argparse
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from src.constants import METRICS_WAIT_HOURS
from src.db.supabase_client import get_campaign, get_client, get_gate_decision
from src.graph.build_graph import build_graph
from src.usage import budget_exhausted, use_org

GATE_NUMBER_BY_STATUS = {"awaiting_gate_1": 1, "awaiting_gate_2": 2}
ACTIVE_STATUSES = ["awaiting_gate_1", "awaiting_gate_2", "awaiting_metrics"]


def _resume_gate(app, campaign: dict) -> None:
    campaign_id = campaign["id"]
    gate_number = GATE_NUMBER_BY_STATUS[campaign["status"]]
    decision_row = get_gate_decision(campaign_id, gate_number, campaign["current_round"])
    if not decision_row or not decision_row.get("decided_at"):
        print(f"Campaign {campaign_id}: still awaiting gate {gate_number} decision. No-op.")
        return
    config = {"configurable": {"thread_id": campaign_id}}
    resume_value = {"decision": decision_row["decision"], "comment": decision_row.get("comment")}
    app.invoke(Command(resume=resume_value), config=config)
    print(f"Campaign {campaign_id}: resumed past gate {gate_number}.")


def _resume_metrics_wait(app, campaign: dict) -> None:
    campaign_id = campaign["id"]
    distributed_at = campaign.get("distributed_at")
    if not distributed_at:
        print(f"Campaign {campaign_id}: awaiting_metrics but no distributed_at recorded yet. No-op.")
        return
    elapsed_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(distributed_at)).total_seconds() / 3600
    if elapsed_hours < METRICS_WAIT_HOURS:
        print(f"Campaign {campaign_id}: only {elapsed_hours:.2f}h of {METRICS_WAIT_HOURS}h elapsed. No-op.")
        return
    config = {"configurable": {"thread_id": campaign_id}}
    app.invoke(Command(resume={"proceed": True}), config=config)
    print(f"Campaign {campaign_id}: resumed past metrics wait.")


def process_campaign(app, campaign_id: str) -> None:
    campaign = get_campaign(campaign_id)
    status = campaign["status"]
    use_org(campaign.get("org_id"))
    # Paused by the circuit breaker: nothing moves until an owner or admin resumes it.
    if campaign.get("paused_at"):
        print(f"Campaign {campaign_id}: paused by the circuit breaker since {campaign['paused_at']}.")
        return
    blocked = budget_exhausted(campaign.get("org_id"))
    if blocked and status != "awaiting_gate_1":  # gate 1 resumes don't need the LLM until creative
        print(f"Campaign {campaign_id}: paused, {blocked}.")
        return
    if status in ("awaiting_gate_1", "awaiting_gate_2"):
        _resume_gate(app, campaign)
    elif status == "awaiting_metrics":
        _resume_metrics_wait(app, campaign)
    else:
        print(f"Campaign {campaign_id}: status '{status}' is not actionable this tick.")


def main() -> None:
    load_dotenv()
    from src.observability import init

    init("campaign-sweep")
    parser = argparse.ArgumentParser(description="Reliability sweep (no args) or resume-one (--campaign-id) for the autonomous campaign loop.")
    parser.add_argument("--campaign-id", default=None)
    args = parser.parse_args()

    with PostgresSaver.from_conn_string(os.environ["SUPABASE_DB_URL"]) as checkpointer:
        checkpointer.setup()
        app = build_graph(checkpointer)

        if args.campaign_id:
            process_campaign(app, args.campaign_id)
            return

        result = get_client().table("campaigns").select("id, status").in_("status", ACTIVE_STATUSES).execute()
        if not result.data:
            print("No active campaigns due for processing.")
            return
        for row in result.data:
            process_campaign(app, row["id"])


if __name__ == "__main__":
    main()
