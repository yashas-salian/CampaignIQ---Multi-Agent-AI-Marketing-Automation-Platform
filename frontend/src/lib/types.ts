import type { FocusGroupResult } from '../components/FocusGroup'
import type { ArmExplanation } from '../components/ArmExplain'
export type CampaignStatus =
  | 'created'
  | 'awaiting_gate_1'
  | 'awaiting_gate_2'
  | 'awaiting_metrics'
  | 'awaiting_next_round'
  | 'completed'
  | 'rejected'

export interface Campaign {
  id: string
  org_id: string
  idea: string
  domain_category: string
  feasibility_score: number | null
  feasibility_rationale: string | null
  status: CampaignStatus
  current_round: number
  reddit_subreddit: string | null
  email_to: string[] | null
  cta_url: string | null
  /** The product photo every ad is built around (bucket product-photos) and its optional tagline. */
  product_image_path?: string | null
  product_tagline?: string | null
  use_image_template: boolean
  use_email_template: boolean
  max_rounds: number | null
  max_duration_minutes: number | null
  campaign_summary: Record<string, unknown> | null
  distributed_at: string | null
  stop_requested: boolean
  target_language: string
  ab_test?: boolean
  ab_decision?: AbDecision | null
  created_at: string
  updated_at: string
}

export interface Persona {
  id: string
  campaign_id: string
  name: string
  demographics: string
  psychographics: string
  channel_fit: string
  messaging_angle: string
  is_primary: boolean
  archetype?: string | null
  gender?: string | null
}

export interface Iteration {
  id: string
  campaign_id: string
  round_number: number
  copy_text: string | null
  image_prompt: string | null
  /** The finished ad in the private ad-images bucket (src/tools/ad_composer.py). */
  image_path?: string | null
  /** How many times the picture was repainted at Gate 2 ("New picture"). */
  image_version?: number
  headline?: string | null
  cta?: string | null
  /** The product-first layout used (src/tools/ad_templates.py); empty for older ads. */
  template?: string | null
  preflight_score: number | null
  preflight_passed: boolean | null
  preflight_attempt: number
  bluesky_post_uri: string | null
  mastodon_post_url: string | null
  reddit_post_url: string | null
  email_id: string | null
  image_style: string | null
  copy_tone: string | null
  arm_index: number | null
  guardrail_flags: GuardrailFlags | null
  arm_explain?: ArmExplanation | null
  focus_group?: FocusGroupResult | null
  copy_text_b?: string | null
  image_style_b?: string | null
  copy_tone_b?: string | null
}

/** Email A/B test outcome (src/capabilities/experiments.py), stored on the variant-B metric. */
export interface AbTestResult {
  rate_a: number
  rate_b: number
  lift: number | null
  p_value: number | null
  significant: boolean
  winner: 'a' | 'b' | null
  /** Bayesian read-out (rounds measured after it was added). */
  bayes?: {
    prob_b_beats_a: number | null
    /** B - A in click rate (the headline number); lift is null when A has no clicks. */
    expected_difference?: number | null
    expected_lift: number | null
    interval: [number, number] | null
    decided: 'a' | 'b' | null
    threshold: number
    min_recipients: number
  }
}

/** A decided A/B test: the split stopped and the winner's style runs for everyone. */
export interface AbDecision {
  winner: 'a' | 'b'
  prob_b_beats_a: number
  round: number
  arm_index: number
  image_style: string
  copy_tone: string
}

/** Brand-safety result for a round's creative (src/capabilities/guardrails.py). */
export interface GuardrailFlags {
  issues: { code: string; severity: 'block' | 'review'; message: string; category?: 'safety' | 'claims' | 'readability' | 'accessibility'; fix?: string | null }[]
  disclaimer: string | null
}

export interface GateDecision {
  id: string
  campaign_id: string
  gate_number: 1 | 2
  round_number: number
  decision: 'approve' | 'edit' | 'reject' | null
  comment: string | null
  decided_at: string | null
}

export interface Metric {
  id: string
  campaign_id: string
  round_number: number
  channel: 'bluesky' | 'mastodon' | 'reddit' | 'email' | 'email_b'
  raw_metrics: Record<string, number | AbTestResult>
  reward: number
  collected_at: string
}
