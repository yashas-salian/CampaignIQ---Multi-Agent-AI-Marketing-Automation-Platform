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
  idea: string
  domain_category: string
  feasibility_score: number | null
  feasibility_rationale: string | null
  status: CampaignStatus
  current_round: number
  reddit_subreddit: string | null
  email_to: string[] | null
  cta_url: string | null
  use_image_template: boolean
  use_email_template: boolean
  max_rounds: number | null
  max_duration_minutes: number | null
  campaign_summary: Record<string, unknown> | null
  distributed_at: string | null
  stop_requested: boolean
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
}

export interface Iteration {
  id: string
  campaign_id: string
  round_number: number
  copy_text: string | null
  image_prompt: string | null
  preflight_score: number | null
  preflight_passed: boolean | null
  preflight_attempt: number
  bluesky_post_uri: string | null
  reddit_post_url: string | null
  email_id: string | null
  image_style: string | null
  copy_tone: string | null
  arm_index: number | null
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
  channel: 'bluesky' | 'reddit' | 'email'
  raw_metrics: Record<string, number>
  reward: number
  collected_at: string
}
