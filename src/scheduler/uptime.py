"""Uptime checks for the public status page (/status).

Run every 15 minutes by .github/workflows/uptime.yml. Each component is one
HTTP probe; results go to `status_checks` (service role). Probes are cheap and
unauthenticated where possible, so the check itself never spends quota.
"""
import os
import time

import requests
from dotenv import load_dotenv

TIMEOUT = 10


def _probe(method: str, url: str, ok_statuses: tuple[int, ...], headers: dict | None = None) -> tuple[bool, int, str | None]:
    started = time.monotonic()
    try:
        response = requests.request(method, url, headers=headers or {}, timeout=TIMEOUT)
        ms = int((time.monotonic() - started) * 1000)
        if response.status_code in ok_statuses:
            return True, ms, None
        return False, ms, f"HTTP {response.status_code}"
    except requests.RequestException as exc:
        return False, int((time.monotonic() - started) * 1000), type(exc).__name__


def checks() -> dict[str, tuple[bool, int, str | None]]:
    site = os.environ.get("APP_BASE_URL", "https://campaign-iq-multi-agent-ai-marketin.vercel.app").rstrip("/")
    supabase = os.environ["SUPABASE_URL"].rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY", "")
    return {
        "website": _probe("GET", site, (200,)),
        # Any answer from PostgREST (incl. 401 without a key) means the API is serving.
        "database_api": _probe("GET", f"{supabase}/rest/v1/", (200, 401), {"apikey": anon} if anon else None),
        "authentication": _probe("GET", f"{supabase}/auth/v1/health", (200, 401), {"apikey": anon} if anon else None),
        # CORS preflight: proves the function runtime is up without running the function.
        "edge_functions": _probe("OPTIONS", f"{supabase}/functions/v1/create-campaign", (200, 204)),
        "public_api": _probe("OPTIONS", f"{supabase}/functions/v1/api", (200, 204)),
    }


def main() -> None:
    load_dotenv()
    # A bare client: src.db.supabase_client imports the AI stack, which this
    # lightweight workflow doesn't install.
    from supabase import create_client

    results = checks()
    rows = [{"component": c, "ok": ok, "latency_ms": ms, "detail": detail} for c, (ok, ms, detail) in results.items()]
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    client.table("status_checks").insert(rows).execute()
    client.rpc("prune_status_checks").execute()
    for r in rows:
        print(f"{r['component']:<16} {'up' if r['ok'] else 'DOWN':<5} {r['latency_ms']:>6} ms  {r['detail'] or ''}")


if __name__ == "__main__":
    main()
