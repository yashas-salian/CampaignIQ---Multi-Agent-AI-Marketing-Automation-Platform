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
def feasibility(idea: str) -> None:
    result = score_feasibility(idea)
    typer.echo(f"Score: {result.score}")
    typer.echo(f"Rationale: {result.rationale}")


@app.command()
def image(prompt: str, out: str = "output.png") -> None:
    data = get_image_generator().generate_image(prompt)
    with open(out, "wb") as f:
        f.write(data)
    typer.echo(f"Wrote {len(data)} bytes to {out}")


@app.command()
def personas(idea: str, n: int = 3) -> None:
    result = score_feasibility(idea)
    for p in generate_personas(idea, result, n=n):
        typer.echo(p.model_dump_json(indent=2))


@app.command()
def creative(
    idea: str,
    persona_name: str = "General audience",
    persona_description: str = "A broad, price-sensitive early adopter.",
    out: str = "creative.png",
) -> None:
    persona = Persona(
        name=persona_name,
        demographics=persona_description,
        psychographics=persona_description,
        channel_fit="social",
        messaging_angle=persona_description,
    )
    result = generate_creative(idea, persona)
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


if __name__ == "__main__":
    app()
