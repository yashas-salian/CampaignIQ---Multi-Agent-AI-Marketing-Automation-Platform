from pydantic import BaseModel

from src.capabilities.metrics import MetricsResult
from src.llm_json import generate_json
from src.providers.registry import get_llm


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
) -> RevisionDirective:
    if current_round >= max_rounds:
        return RevisionDirective(
            continue_campaign=False,
            reasoning=f"Reached the round cap ({max_rounds}) for this campaign's tier.",
            adjustments="",
        )

    parsed = generate_json(
        get_llm(user_id),
        f'Ad campaign idea: "{idea}"\n'
        f"Round {current_round} results: overall_reward={metrics.overall_reward:.2f} (0-1 scale), "
        f"per-channel rewards: {metrics.channel_rewards}\n"
        f"Stakeholder feedback: {stakeholder_comment or 'none'}\n\n"
        "Decide whether this campaign should continue to another round, and if so, what should "
        "be adjusted (tone, image style, channel emphasis, etc.) for the next round's creative. "
        "Respond with ONLY a JSON object, no prose, with exactly three keys: "
        '"continue_campaign" (boolean), "reasoning" (one sentence), "adjustments" (a short '
        'directive to feed into the next round\'s creative generation, empty string if not continuing).',
        system="You are a marketing performance analyst deciding whether a campaign is working. "
        "You output only valid JSON, never prose or markdown fences.",
    )
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
