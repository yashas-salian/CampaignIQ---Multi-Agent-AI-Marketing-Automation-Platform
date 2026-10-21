from pydantic import BaseModel

from src.capabilities.metrics import MetricsResult
from src.languages import language_name
from src.llm_json import generate_json
from src.providers.registry import get_llm
from src.prompts import PROMPTS
from src.security.prompt_guard import fence


class RevisionDirective(BaseModel):
    continue_campaign: bool
    reasoning: str
    adjustments: str


def run_feedback_correction(
    idea: str,
    metrics: MetricsResult,
    current_round: int,
    max_rounds: int,
    *,
    stakeholder_comment: str | None = None,
    user_id: str | None = None,
    target_language: str = "en",
) -> RevisionDirective:
    if current_round >= max_rounds:
        return RevisionDirective(
            continue_campaign=False,
            reasoning=f"Reached the round cap ({max_rounds}) for this campaign's tier.",
            adjustments="",
        )

    prompt, system = PROMPTS["feedback.decide"].render(
        idea=fence(idea, "user_idea"),
        round=current_round,
        reward=f"{metrics.overall_reward:.2f}",
        channel_rewards=metrics.channel_rewards,
        comment=fence(stakeholder_comment or "none", "stakeholder_comment"),
        language=language_name(target_language),
    )
    parsed = generate_json(get_llm(user_id), prompt, system=system)
    return RevisionDirective(**parsed)


def build_campaign_summary(campaign_id: str) -> dict:
    from src.db.supabase_client import get_all_iterations, get_all_metrics

    iterations = get_all_iterations(campaign_id)
    metrics_rows = get_all_metrics(campaign_id)

    reward_by_round: dict[int, list[float]] = {}
    for m in metrics_rows:
        reward_by_round.setdefault(m["round_number"], []).append(float(m["reward"]))
    reward_trend = [
        {"round": round_number, "reward": sum(rewards) / len(rewards)}
        for round_number, rewards in sorted(reward_by_round.items())
    ]

    total_engagement: dict[str, float] = {}
    for m in metrics_rows:
        for key, value in m["raw_metrics"].items():
            if isinstance(value, (int, float)):
                metric_key = f"{m['channel']}_{key}"
                total_engagement[metric_key] = total_engagement.get(metric_key, 0) + value

    winning_round = max(reward_trend, key=lambda r: r["reward"]) if reward_trend else None

    return {
        "total_rounds": len(iterations),
        "winning_round": winning_round,
        "reward_trend": reward_trend,
        "total_engagement": total_engagement,
    }
