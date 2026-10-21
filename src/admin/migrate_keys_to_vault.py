"""One-off: move legacy AES-encrypted BYOK keys into Supabase Vault.

Rows saved before the Vault migration hold `encrypted_key` (AES-GCM with
SETTINGS_ENCRYPTION_KEY). This decrypts each one and re-stores it through
store_provider_key(), which puts it in Vault and clears the ciphertext.
Idempotent: rows already in Vault are skipped. Run with the service role:

    python -m src.admin.migrate_keys_to_vault            # dry run: counts only
    python -m src.admin.migrate_keys_to_vault --apply

Afterwards SETTINGS_ENCRYPTION_KEY is no longer needed anywhere.
"""
import argparse

from dotenv import load_dotenv

from src.db.supabase_client import get_client
from src.providers.crypto import decrypt_key


def migrate(apply: bool) -> dict[str, int]:
    rows = (
        get_client()
        .table("provider_keys")
        .select("user_id,capability,encrypted_key")
        .is_("vault_secret_id", "null")
        .not_.is_("encrypted_key", "null")
        .execute()
        .data
    )
    counts = {"legacy": len(rows), "moved": 0, "failed": 0}
    for row in rows:
        label = f"user {row['user_id'][:8]}… {row['capability']}"
        try:
            raw = decrypt_key(row["encrypted_key"])
            if apply:
                get_client().rpc(
                    "store_provider_key",
                    {"p_user_id": row["user_id"], "p_capability": row["capability"], "p_api_key": raw},
                ).execute()
            counts["moved"] += 1
            print(f"{'moved' if apply else 'would move'}: {label}")
        except Exception as exc:  # wrong SETTINGS_ENCRYPTION_KEY, corrupt row
            counts["failed"] += 1
            print(f"FAILED: {label}: {type(exc).__name__}")
    return counts


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="actually move the keys (default: dry run)")
    counts = migrate(parser.parse_args().apply)
    print(f"legacy rows: {counts['legacy']}, moved: {counts['moved']}, failed: {counts['failed']}")


if __name__ == "__main__":
    main()
