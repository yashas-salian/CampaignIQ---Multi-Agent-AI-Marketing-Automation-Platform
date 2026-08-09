import os
import uuid

import typer
from dotenv import load_dotenv

from src.capabilities.audience import generate_personas
from src.capabilities.creative import generate_creative, Persona
from src.capabilities.distribution import post_bluesky, post_reddit, send_campaign_email
from src.capabilities.feasibility import score_feasibility
from src.providers.registry import get_image_generator

load_dotenv()
app = typer.Typer(help="Standalone, one-off runs of each capability, independent of the LangGraph pipeline.")


@app.command()
def feasibility(idea: str, user_id: str = "") -> None:
    result = score_feasibility(idea, user_id=user_id or None)
    typer.echo(f"Score: {result.score}")
    typer.echo(f"Rationale: {result.rationale}")


@app.command()
def image(prompt: str, out: str = "output.png", user_id: str = "") -> None:
    data = get_image_generator(user_id or None).generate_image(prompt)
    with open(out, "wb") as f:
        f.write(data)
    typer.echo(f"Wrote {len(data)} bytes to {out}")


@app.command()
def personas(idea: str, n: int = 3, user_id: str = "") -> None:
    result = score_feasibility(idea, user_id=user_id or None)
    for p in generate_personas(idea, result, n=n, user_id=user_id or None):
        typer.echo(p.model_dump_json(indent=2))


@app.command()
def creative(
    idea: str,
    persona_name: str = "General audience",
    persona_description: str = "A broad, price-sensitive early adopter.",
    out: str = "creative.png",
    user_id: str = "",
) -> None:
    persona = Persona(
        name=persona_name,
        demographics=persona_description,
        psychographics=persona_description,
        channel_fit="social",
        messaging_angle=persona_description,
    )
    result = generate_creative(idea, persona, user_id=user_id or None)
    with open(out, "wb") as f:
        f.write(result.image_bytes)
    typer.echo(f"Copy: {result.copy_text}")
    typer.echo(f"Image prompt: {result.image_prompt}")
    typer.echo(f"Wrote image to {out}")


@app.command("post-bluesky")
def post_bluesky_cmd(text: str, campaign_id: str = "", round_id: int = 1) -> None:
    result = post_bluesky(campaign_id or str(uuid.uuid4()), round_id, text)
    typer.echo(f"Result: {result}")


@app.command("post-reddit")
def post_reddit_cmd(subreddit: str, title: str, body: str, campaign_id: str = "", round_id: int = 1) -> None:
    result = post_reddit(campaign_id or str(uuid.uuid4()), round_id, subreddit, title, body)
    typer.echo(f"Result: {result}")


@app.command("send-email")
def send_email_cmd(
    subject: str,
    body: str,
    to: str = "",
    cta_url: str = "",
    campaign_id: str = "",
    round_id: int = 1,
) -> None:
    recipients = to.split(",") if to else [os.environ["RESEND_TEST_TO_EMAIL"]]
    result = send_campaign_email(
        campaign_id or str(uuid.uuid4()),
        round_id,
        recipients,
        subject,
        f"<p>{body}</p>",
        cta_url=cta_url or None,
    )
    typer.echo(f"Result: {result}")


admin_app = typer.Typer(help="Admin/operator commands.")
app.add_typer(admin_app, name="admin")


@admin_app.command("set-subscription")
def set_subscription(email: str, status: str) -> None:
    if status not in ("free", "subscribed"):
        typer.echo('status must be "free" or "subscribed"')
        raise typer.Exit(code=1)

    from src.db.supabase_client import get_client

    client = get_client()
    users = client.auth.admin.list_users()
    match = next((u for u in users if u.email == email), None)
    if not match:
        typer.echo(f"No user found with email {email!r}")
        raise typer.Exit(code=1)

    client.table("subscriptions").upsert({"user_id": match.id, "status": status}).execute()
    typer.echo(f"{email} ({match.id}) is now '{status}'")


if __name__ == "__main__":
    app()
