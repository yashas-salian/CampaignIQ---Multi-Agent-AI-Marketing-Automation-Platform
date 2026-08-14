import argparse
import sys

from dotenv import load_dotenv

from src.db.supabase_client import get_client


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Operator-only: toggle a user's subscription tier. Not part of the product's "
        "own UI since this is a billing action performed by the operator, not the end user."
    )
    parser.add_argument("email")
    parser.add_argument("status", choices=["free", "subscribed"])
    args = parser.parse_args()

    client = get_client()
    users = client.auth.admin.list_users()
    match = next((u for u in users if u.email == args.email), None)
    if not match:
        print(f"No user found with email {args.email!r}")
        sys.exit(1)

    client.table("subscriptions").upsert({"user_id": match.id, "status": args.status}).execute()
    print(f"{args.email} ({match.id}) is now '{args.status}'")


if __name__ == "__main__":
    main()
