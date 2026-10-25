import argparse
import os
import uuid

from dotenv import load_dotenv
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command

from src.db.supabase_client import get_campaign, get_gate_decision
from src.graph.build_graph import build_graph
from src.languages import SUPPORTED_LANGUAGES
from src.usage import budget_exhausted, personal_org, use_org

GATE_NUMBER_BY_STATUS = {"awaiting_gate_1": 1, "awaiting_gate_2": 2}


def _checkpointer():
    return PostgresSaver.from_conn_string(os.environ["SUPABASE_DB_URL"])


def main() -> None:
    load_dotenv()
    from src.observability import init

    init("campaign-run")
    parser = argparse.ArgumentParser(description="Trigger or resume one campaign run.")
    parser.add_argument("idea", nargs="?", help="New campaign idea (omit when resuming --campaign-id)")
    parser.add_argument("--campaign-id", default=None, help="Resume an existing campaign instead of creating one")
    parser.add_argument("--user-id", default=None, help="Owning user's Supabase Auth id (required for a new campaign)")
    parser.add_argument("--org-id", default=None, help="Organisation the campaign belongs to (default: the user's personal one)")
    parser.add_argument("--email-to", default="", help="Comma-separated recipient list")
    parser.add_argument("--ab-test", action="store_true", help="Email A/B test: two variants per round, list split in half")
    parser.add_argument("--reddit-subreddit", default=None)
    parser.add_argument("--cta-url", default=None)
    parser.add_argument("--product-image", default=None, help="Path of the product photo in the product-photos bucket")
    parser.add_argument("--tagline", default=None, help="Optional product tagline set on every ad")
    parser.add_argument("--use-image-template", action="store_true", help="Use this user's stored image template instead of generating one")
    parser.add_argument("--use-email-template", action="store_true", help="Use this user's stored email template instead of the default layout")
    parser.add_argument(
        "--target-language", default="en", choices=list(SUPPORTED_LANGUAGES),
        help="Language for generated content (copy, personas, rationale) and localized research signals",
    )
    args = parser.parse_args()

    with _checkpointer() as checkpointer:
        checkpointer.setup()
        app = build_graph(checkpointer)

        if args.campaign_id:
            campaign_id = args.campaign_id
            campaign = get_campaign(campaign_id)
            use_org(campaign.get("org_id"))
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
            org_id = args.org_id or personal_org(args.user_id)
            use_org(org_id)
            blocked = budget_exhausted(org_id)
            if blocked:
                print(f"Not starting: {blocked}")
                return
            campaign_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": campaign_id}}
            initial_state = {
                "idea": args.idea, "campaign_id": campaign_id, "user_id": args.user_id, "round_id": 1,
                "org_id": org_id,
                "ab_test": args.ab_test,
                "email_to": args.email_to.split(",") if args.email_to else [os.environ["RESEND_TEST_TO_EMAIL"]],
                "reddit_subreddit": args.reddit_subreddit, "cta_url": args.cta_url or None,
                "product_image_path": args.product_image or None, "product_tagline": (args.tagline or "").strip()[:80] or None,
                "use_image_template": args.use_image_template, "use_email_template": args.use_email_template,
                "target_language": args.target_language,
            }
            app.invoke(initial_state, config=config)
            print(f"New campaign created: {campaign_id}")

        print(f"Campaign {campaign_id} status: {get_campaign(campaign_id)['status']}")


if __name__ == "__main__":
    main()
