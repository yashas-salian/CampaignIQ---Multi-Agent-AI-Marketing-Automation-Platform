"""Grant or revoke platform-operator access to the /admin console.

    python -m src.admin.make_admin you@example.com
    python -m src.admin.make_admin you@example.com --revoke

Runs with the service role from .env. Operators can override plans, retry dead
sends and toggle feature flags for every organisation, so keep the list short.
"""
import argparse

from dotenv import load_dotenv

from src.db.supabase_client import get_client


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    parser.add_argument("--revoke", action="store_true")
    args = parser.parse_args()

    client = get_client()
    users = client.auth.admin.list_users()
    user = next((u for u in users if (u.email or "").lower() == args.email.lower()), None)
    if not user:
        raise SystemExit(f"no user with email {args.email}")
    if args.revoke:
        client.table("platform_admins").delete().eq("user_id", user.id).execute()
        print(f"{args.email} is no longer a platform admin")
    else:
        client.table("platform_admins").upsert({"user_id": user.id}).execute()
        print(f"{args.email} is now a platform admin: open /admin")


if __name__ == "__main__":
    main()
