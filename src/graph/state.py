from typing import Optional, TypedDict

from src.capabilities.audience import Persona
from src.capabilities.creative import Creative
from src.capabilities.feasibility import FeasibilityResult
from src.capabilities.idea_intake import DomainCategory


class CampaignState(TypedDict, total=False):
    idea: str
    campaign_id: str
    round_id: int
    domain_category: DomainCategory
    reddit_subreddit: str
    email_to: list[str]
    cta_url: Optional[str]
    feasibility: FeasibilityResult
    personas: list[Persona]
    creative: Creative
    bluesky_post_uri: Optional[str]
    reddit_post_url: Optional[str]
    email_id: Optional[str]
