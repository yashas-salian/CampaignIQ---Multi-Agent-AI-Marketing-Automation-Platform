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
  /** Stopped by a hard block in the decision engine (src/capabilities/decision.py). */
  | 'blocked'

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
  /** When the offer in the ads ends; past it, the circuit breaker pauses the campaign. */
  offer_ends_at?: string | null
  /** Set while the circuit breaker holds the campaign (src/capabilities/circuit_breaker.py). */
  paused_at?: string | null
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

/** The decision engine's recommendation (table campaign_decisions; src/capabilities/decision.py). */
export type DecisionOutcome = 'LAUNCH' | 'TEST_SMALL' | 'WAIT' | 'KILL' | 'INSUFFICIENT_EVIDENCE'

export interface DecisionFactor {
  key: 'demand' | 'momentum' | 'purchase_intent' | 'competition' | 'reachability' | 'track_record'
  weight: number
  score: number | null
  value: string
  source: string
  reliability: 'measured' | 'proxy' | 'estimate'
  fetched_at?: string | null
  available: boolean
  stale: boolean
  note?: string
}

export interface CampaignDecision {
  id?: string
  campaign_id?: string
  decision: DecisionOutcome
  opportunity_score: number | null
  uncertainty: number
  reason_codes: string[]
  factors: DecisionFactor[]
  hard_blocks: { code: string; detail: string }[]
  review_flags: { code: string; detail: string }[]
  constraints: { max_rounds?: number }
  reevaluate: { type: string; keyword: string; threshold: number } | null
  baseline: { rule: string; decision: 'LAUNCH' | 'KILL' | null }
  policy_version: string
  trigger?: 'initial' | 'reevaluation'
  outcome?: { rounds?: number; best_reward?: number; mean_reward?: number } | null
  created_at?: string
  evaluated_at?: string
}

/** The crash test before Gate 2 (table crash_tests; src/capabilities/crash_test.py). */
export type CrashSeverity = 'low' | 'medium' | 'high' | 'critical'
export type CrashRisk = 'clear' | CrashSeverity

export interface CrashFinding {
  key: string
  source: 'rule' | 'simulation'
  scenario: string | null
  type: string
  severity: CrashSeverity
  quote: string | null
  field: 'body' | 'headline' | 'cta' | null
  problem: string
  fix: string
}

export interface CrashAd {
  body: string
  headline: string
  cta: string
  visual?: string
}

export interface CrashReport {
  scenario_set: string
  rules_version: string
  simulation_only: boolean
  status: 'COMPLETED' | 'RULES_ONLY'
  ad: CrashAd
  findings: CrashFinding[]
  risk: CrashRisk
  counts: Record<CrashSeverity, number>
  revised: CrashAd | null
  revision_notes: string[]
  revised_findings: CrashFinding[]
  revised_risk: CrashRisk | null
  comparison: { resolved: string[]; remaining: string[]; new: string[] } | null
  note: string
  created_at: string
}

export interface CrashTestRow {
  id: string
  round_number: number
  trigger: 'pipeline' | 'rerun'
  risk: CrashRisk
  revised_risk: CrashRisk | null
  report: CrashReport
  applied_at: string | null
  created_at: string
}

/** A circuit-breaker hold (table campaign_holds). Critical ones pause sending. */
export type HoldTrigger = 'EXPIRED_OFFER' | 'INVALID_DESTINATION' | 'POLICY_VIOLATION' | 'REVOKED_APPROVAL' | 'BRAND_RISK' | 'MANUAL_STOP'

export interface CampaignHold {
  id: string
  channel: string | null
  trigger: HoldTrigger
  severity: 'critical' | 'warning'
  status: 'active' | 'resolved' | 'false_alarm'
  detail: string
  evidence: Record<string, unknown>
  signal_at: string | null
  created_at: string
  created_by: string | null
  resolved_at: string | null
  resolution_note: string | null
}

/** Proof of impact (table experiments; analysis by src/capabilities/impact.py). */
export type ImpactMetric = 'qualified_signup_rate' | 'conversion_rate' | 'click_through_rate'
export type ImpactStatus = 'COLLECTING' | 'POSITIVE_IMPACT' | 'NEGATIVE_IMPACT' | 'NO_MEANINGFUL_IMPACT' | 'INCONCLUSIVE'
export type ImpactArm = 'control' | 'treatment' | 'treatment_b'

export interface ImpactEstimate {
  treatment_arms: ImpactArm[]
  control_arms: ImpactArm[]
  treatment_units: number
  control_units: number
  treatment_successes: number
  control_successes: number
  treatment_rate: number | null
  control_rate: number | null
  absolute_lift: number | null
  interval: [number, number] | null
  prob_treatment_better: number | null
  relative_lift: number | null
  relative_interval: [number, number] | null
  relative_note: string | null
  incremental_successes: number | null
  incremental_interval: [number, number] | null
  causal: boolean
}

export interface ImpactArmStats {
  units: number
  exposed: number
  clickers: number
  converters: number
  qualified: number
  successes: number
  rate: number | null
  rate_interval: [number, number] | null
  revenue: number
  revenue_per_unit: number | null
}

export interface ImpactResult {
  policy_version: string
  status: ImpactStatus
  reason: string
  final: boolean
  interim: boolean
  primary_metric: ImpactMetric
  design: 'holdout' | 'holdout_ab' | 'ab'
  min_effect: number
  practically_significant: boolean
  window: { started_at: string | null; ends_at: string | null; analysis_at: string | null; attribution_window_days: number }
  arms: Partial<Record<ImpactArm, ImpactArmStats>>
  estimate: ImpactEstimate
  secondary: ImpactEstimate | null
  revenue: {
    currency: string | null
    mixed_currencies: boolean
    incremental_revenue: number | null
    incremental_interval: [number, number] | null
    average_conversion_value?: number
    attributed_revenue: number
    attribution_model: string
  } | null
  quality: {
    srm_p_value: number | null
    sample_ratio_mismatch: boolean
    expected_shares: Partial<Record<ImpactArm, number>>
    min_units_per_arm: number
    smallest_group: number
    conversions_received: number
    unmatched_conversions: number
    last_exposure_at: string | null
    last_click_at: string | null
    last_conversion_at: string | null
    stale_outcomes: boolean
    no_conversions_yet: boolean
  }
  assumptions: string[]
  recommended_action: string | null
  analyzed_at: string
  bandit?: { fed: boolean; reason?: string; rewards?: { round: number; arm: ImpactArm; units: number; successes: number; reward: number }[] }
}

export interface Experiment {
  id: string
  campaign_id: string
  hypothesis: string
  primary_metric: ImpactMetric
  design: 'holdout' | 'holdout_ab' | 'ab'
  control_share: number
  attribution_window_days: number
  duration_days: number
  min_units_per_arm: number
  min_effect: number
  baseline_rate: number | null
  policy_version: string
  status: 'declared' | 'running' | 'completed'
  started_at: string | null
  ends_at: string | null
  analysis_at: string | null
  result: ImpactResult | null
  result_status: ImpactStatus | null
  analyzed_at: string | null
  concluded_at: string | null
}

/** Competitor intelligence (src/capabilities/competitors.py). */
export type CompetitorEventKind = 'OFFER_CHANGE' | 'MESSAGING_SHIFT' | 'PRODUCT_LAUNCH' | 'CONTENT_THEME'
export type CompetitorAction = 'RESPOND' | 'MONITOR' | 'DIFFERENTIATE' | 'NO_ACTION'
export type SourceKind = 'webpage' | 'rss' | 'news' | 'bluesky'
export type SourceStatus = 'never' | 'ok' | 'stale' | 'unavailable' | 'blocked_by_robots'

export interface CompetitorSource {
  id: string
  kind: SourceKind
  locator: string
  approved: boolean
  status: SourceStatus
  last_fetched_at: string | null
  last_ok_at: string | null
  last_error: string | null
}

export interface Competitor {
  id: string
  org_id: string
  name: string
  website: string | null
  keywords: string[]
  category_keyword: string | null
  markets: string[]
  created_at: string
  competitor_sources?: CompetitorSource[]
}

export interface CompetitorEvent {
  id: string
  kind: CompetitorEventKind
  summary: string
  observed: Record<string, unknown>
  url: string | null
  outlet: string | null
  published_at: string | null
  observed_at: string
  reports: number
  outlets: string[]
  original_outlet: string | null
  confidence: number
}

export interface CompetitorInsight {
  id: string
  event_id: string
  recommendation: CompetitorAction
  options: { action: CompetitorAction; recommended: boolean; reasons: string[] }[]
  explanations: { hypothesis?: string; hypothesis_code?: string; would_confirm?: string; would_refute?: string; inferred: true; source: 'llm' | 'template' }[]
  confidence: number
  relevance: { relevant?: boolean; live_campaigns?: { id: string; idea: string }[]; history?: Record<string, unknown> }
  status: 'open' | 'acted' | 'dismissed'
  note: string | null
}

export interface CompetitorPrediction {
  id: string
  event_id: string | null
  keyword: string
  horizon_days: number
  origin_week: string
  predicted_change: number
  interval_low: number
  interval_high: number
  interval_level: number
  model_version: string
  status: 'pending' | 'resolved' | 'unresolvable'
  observed_change: number | null
  inside_interval: boolean | null
  materialized: boolean | null
  resolve_after: string
}
