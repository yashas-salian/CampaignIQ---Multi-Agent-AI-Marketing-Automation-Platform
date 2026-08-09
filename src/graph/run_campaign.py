import argparse
import os
import uuid

from dotenv import load_dotenv
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from src.db.supabase_client import get_campaign, get_gate_decision
from src.graph.build_graph import build_graph

CHECKPOINT_DB = os.environ.get("CHECKPOINT_DB_PATH", ".langgraph_checkpoints.sqlite")
GATE_NUMBER_BY_STATUS = {"awaiting_gate_1": 1, "awaiting_gate_2": 2}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Trigger or resume one campaign run (M3: single-tenant, local).")
    parser.add_argument("idea", nargs="?", help="New campaign idea (omit when resuming --campaign-id)")
    parser.add_argument("--campaign-id", default=None, help="Resume an existing campaign instead of creating one")
    parser.add_argument("--user-id", default=None, help="Owning user's Supabase Auth id (required for a new campaign)")
    parser.add_argument("--email-to", default="", help="Comma-separated recipient list")
    parser.add_argument("--reddit-subreddit", default=None)
    parser.add_argument("--cta-url", default=None)
    args = parser.parse_args()

    with SqliteSaver.from_conn_string(CHECKPOINT_DB) as checkpointer:
        app = build_graph(checkpointer)

        if args.campaign_id:
            campaign_id = args.campaign_id
            campaign = get_campaign(campaign_id)
            gate_number = GATE_NUMBER_BY_STATUS.get(campaign["status"])
            if gate_number is None:
                print(f"Campaign {campaign_id} is in status '{campaign['status']}' — nothing to resume.")
                return

            decision_row = get_gate_decision(campaign_id, gate_number, campaign["current_round"])
            if not decision_row or not decision_row.get("decided_at"):
                print(f"Campaign {campaign_id} still awaiting gate {gate_number} decision. No-op.")
                return

            config = {"configurable": {"thread_id": campaign_id}}
            resume_value = {"decision": decision_row["decision"], "comment": decision_row.get("comment")}
            app.invoke(Command(resume=resume_value), config=config)
        else:
            if not args.idea:
                parser.error("an idea is required when not resuming with --campaign-id")
            if not args.user_id:
                parser.error("--user-id is required when creating a new campaign")
            campaign_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": campaign_id}}
            initial_state = {
                "idea": args.idea,
                "campaign_id": campaign_id,
                "user_id": args.user_id,
                "round_id": 1,
                "email_to": args.email_to.split(",") if args.email_to else [os.environ["RESEND_TEST_TO_EMAIL"]],
                "reddit_subreddit": args.reddit_subreddit,
                "cta_url": args.cta_url,
            }
            app.invoke(initial_state, config=config)
            print(f"New campaign created: {campaign_id}")

        print(f"Campaign {campaign_id} status: {get_campaign(campaign_id)['status']}")


if __name__ == "__main__":
    main()
