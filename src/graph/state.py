from typing import Optional, TypedDict

from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.capabilities.feasibility import FeasibilityResult
from src.capabilities.idea_intake import DomainCategory
from src.capabilities.metrics import MetricsResult
from src.capabilities.preflight import PreflightResult


class CampaignState(TypedDict, total=False):
    idea: str
    campaign_id: str
    user_id: str
    round_id: int
    domain_category: DomainCategory
    reddit_subreddit: str
    email_to: list[str]
    cta_url: Optional[str]
    use_image_template: bool
    use_email_template: bool
    feasibility: FeasibilityResult
    personas: list[Persona]
    primary_persona: Persona
    creative: Creative
    preflight: PreflightResult
    preflight_attempt: int
    best_creative: Creative
    best_preflight: PreflightResult
    rejected: bool
    bluesky_post_uri: Optional[str]
    reddit_post_url: Optional[str]
    email_id: Optional[str]
    metrics_result: MetricsResult
    continue_campaign: bool
    revision_directive: Optional[str]
