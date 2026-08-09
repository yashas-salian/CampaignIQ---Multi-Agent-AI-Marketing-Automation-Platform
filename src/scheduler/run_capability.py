import argparse
import base64
import json
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

from src.db.supabase_client import get_client


def _run_feasibility(params: dict, user_id: str) -> dict:
    from src.capabilities.feasibility import score_feasibility

    result = score_feasibility(params["idea"], user_id=user_id)
    return result.model_dump()


def _run_personas(params: dict, user_id: str) -> list[dict]:
    from src.capabilities.audience import generate_personas
    from src.capabilities.feasibility import score_feasibility

    feasibility = score_feasibility(params["idea"], user_id=user_id)
    personas = generate_personas(params["idea"], feasibility, n=params.get("n", 3), user_id=user_id)
    return [p.model_dump() for p in personas]


def _run_creative(params: dict, user_id: str) -> dict:
    from src.capabilities.creative import Persona, generate_creative

    persona = Persona(**params["persona"])
    result = generate_creative(params["idea"], persona, user_id=user_id)
    return {
        "copy_text": result.copy_text,
        "image_prompt": result.image_prompt,
        "image_base64": base64.b64encode(result.image_bytes).decode(),
    }


def _run_image(params: dict, user_id: str) -> dict:
    from src.providers.registry import get_image_generator

    data = get_image_generator(user_id).generate_image(params["prompt"])
    return {"image_base64": base64.b64encode(data).decode()}


CAPABILITY_DISPATCH = {
    "feasibility": _run_feasibility,
    "personas": _run_personas,
    "creative": _run_creative,
    "image": _run_image,
}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="GitHub Actions entrypoint for a single Tools-page capability run.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--params", default="{}")
    args = parser.parse_args()

    client = get_client()
    params = json.loads(args.params)

    client.table("capability_runs").update({"status": "running"}).eq("id", args.run_id).execute()

    handler = CAPABILITY_DISPATCH.get(args.capability)
    if not handler:
        client.table("capability_runs").update(
            {"status": "failed", "error": f"Unknown capability: {args.capability}"}
        ).eq("id", args.run_id).execute()
        sys.exit(1)

    try:
        result = handler(params, args.user_id)
        client.table("capability_runs").update(
            {
                "status": "completed",
                "result": result,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", args.run_id).execute()
    except Exception as exc:
        client.table("capability_runs").update({"status": "failed", "error": str(exc)}).eq("id", args.run_id).execute()
        raise


if __name__ == "__main__":
    main()
