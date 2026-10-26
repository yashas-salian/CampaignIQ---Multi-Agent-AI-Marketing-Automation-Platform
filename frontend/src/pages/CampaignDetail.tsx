import type { CSSProperties } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { useSession } from '../lib/useAuth'
import { useOrg } from '../lib/useOrg'
import CampaignComments from '../components/CampaignComments'
import CopyEditor from '../components/CopyEditor'
import ArmExplain from '../components/ArmExplain'
import ComplianceRadar from '../components/ComplianceRadar'
import FocusGroup from '../components/FocusGroup'
import NewPicture from '../components/NewPicture'
import MarketMoments, { type MarketAlert } from '../components/MarketMoments'
import PersonaChat from '../components/PersonaChat'
import PersonaStage from '../components/PersonaStage'
import { archetypeFor } from '../lib/archetypes'
import { toast } from '../lib/toast'
import { toastFailure, toastLoadError } from '../lib/notify'
import { usePageLoading } from '../lib/loading'
import { supabase } from '../lib/supabaseClient'
import type { Campaign, CampaignDecision, CampaignHold, CampaignStatus, CreativeIntervention, CrashTestRow, Experiment, FatigueAlert, FatigueReport, GateDecision, Iteration, Persona } from '../lib/types'
import CreativeFatigue from '../components/CreativeFatigue'
import ProofOfImpact from '../components/ProofOfImpact'
import { PausedPanel, SafetyControls } from '../components/CircuitBreaker'
import CrashTestReport from '../components/CrashTestReport'
import DecisionCard from '../components/DecisionCard'
import EmailAudience from '../components/EmailAudience'
import styles from '../styles/app.module.css'
import local from './CampaignDetail.module.css'
import Select from '../components/Select'
import { DOMAINS } from '../lib/domains'

const GATE_NUMBER_BY_STATUS: Partial<Record<CampaignStatus, 1 | 2>> = {
  awaiting_gate_1: 1,
  awaiting_gate_2: 2,
}

const STEPS = ['s_intake', 's_feasibility', 's_audience', 's_gate1', 's_creative', 's_preflight', 's_gate2', 's_distribute', 's_measure'] as const

/** Index of the step the campaign is on now (STEPS.length = all done). */
function currentStep(status: CampaignStatus): number {
  switch (status) {
    case 'created':
      return 1
    case 'awaiting_gate_1':
      return 3
    case 'awaiting_next_round':
      return 4
    case 'awaiting_gate_2':
      return 6
    case 'awaiting_metrics':
      return 8
    case 'completed':
      return STEPS.length
    case 'rejected':
    case 'blocked':
      return -1
  }
}

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Brand-safety findings for one round's copy: blocking issues stop the send, claims need a human look. */
/** at://did/app.bsky.feed.post/rkey → public bsky.app URL. */
function blueskyUrl(uri: string) {
  const m = uri.match(/^at:\/\/([^/]+)\/app\.bsky\.feed\.post\/([^/]+)$/)
  return m ? `https://bsky.app/profile/${m[1]}/post/${m[2]}` : null
}

/** Deterministic seed per round, so a round always previews the same picture. */
function seedOf(id: string) {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h % 1_000_000
}

/**
 * The finished ad (headline and CTA set on the picture), from the
 * private ad-images bucket. Older rounds have no stored image, so they get a
 * preview re-drawn from the round's prompt via Pollinations, the same free
 * service the backend falls back to. Falls back to a placeholder.
 */
function RoundImage({ prompt, path, seedFrom, version = 0 }: { prompt: string | null; path?: string | null; seedFrom: string; version?: number }) {
  const { t } = useTranslation()
  const [stored, setStored] = useState<string | null>(null)
  const [storedFailed, setStoredFailed] = useState(!path)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(path || prompt ? 'loading' : 'error')
  useEffect(() => {
    if (!path) return
    let live = true
    supabase.storage
      .from('ad-images')
      .createSignedUrl(path, 3600)
      .then(({ data, error }) => {
        if (!live) return
        if (error || !data?.signedUrl) {
          setStoredFailed(true)
          if (!prompt) setState('error')
        } else setStored(data.signedUrl)
      })
    return () => {
      live = false
    }
  }, [path, prompt, version])
  const preview = prompt
    ? `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=512&height=512&nologo=true&seed=${seedOf(seedFrom)}`
    : ''
  const src = stored ?? (storedFailed ? preview : '')
  if (state === 'error') {
    return (
      <div className={`${styles.placeholder} ${local.creativeImg}`}>
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <path d="M3 15l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
        <span className={styles.placeholderLabel}>{t('cd.imagePlaceholder')}</span>
      </div>
    )
  }
  return (
    <figure className={`${local.creativeImg} ${local.preview} ${state === 'ready' ? local.previewReady : ''}`}>
      {state === 'loading' && <span className={`${styles.skeleton} ${local.previewSkeleton}`} aria-hidden="true" />}
      {src && (
        <img
          src={src}
          alt={prompt ?? ''}
          loading="lazy"
          decoding="async"
          onLoad={() => setState('ready')}
          onError={() => {
            // A stored ad that won't load still has the prompt preview to fall back on.
            if (stored && prompt) {
              setStored(null)
              setStoredFailed(true)
            } else setState('error')
          }}
        />
      )}
      {/* The finished ad carries its own words and button: no overlay on it (screen readers still get the note). */}
      {stored ? <figcaption className={styles.srOnly}>{t('cd.postedNote')}</figcaption> : storedFailed && <figcaption>{t('cd.previewNote')}</figcaption>}
    </figure>
  )
}

function StatusPill({ status, paused }: { status: CampaignStatus; paused?: boolean }) {
  const { t } = useTranslation()
  if (paused) {
    return (
      <span className={`${styles.pill} ${styles.pillRejected}`} data-testid="paused-pill">
        <span className={styles.pillDot} aria-hidden="true" />
        {t('circuit.pausedPill')}
      </span>
    )
  }
  const tone =
    status === 'awaiting_gate_1' || status === 'awaiting_gate_2'
      ? styles.pillAction
      : status === 'completed'
        ? styles.pillDone
        : status === 'rejected' || status === 'blocked'
          ? styles.pillRejected
          : styles.pillRunning
  return (
    <span className={`${styles.pill} ${tone}`}>
      <span className={styles.pillDot} aria-hidden="true" />
      {t(`dash.st_${status}`)}
    </span>
  )
}

/** Feasibility as a ring; the number stays in text ink. */
function ScoreRing({ score }: { score: number | null }) {
  const { t } = useTranslation()
  const r = 52
  const c = 2 * Math.PI * r
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  return (
    <div className={local.ring}>
      <svg viewBox="0 0 128 128" aria-hidden="true">
        <circle cx="64" cy="64" r={r} className={local.ringTrack} />
        <circle
          cx="64"
          cy="64"
          r={r}
          className={local.ringFill}
          style={{ strokeDasharray: c, '--offset': c * (1 - pct) } as CSSProperties}
        />
      </svg>
      <div className={local.ringLabel}>
        <strong>{score ?? '—'}</strong>
        <span>{t('cd.outOf')}</span>
      </div>
    </div>
  )
}

interface GateVote {
  user_id: string
  decision: 'approve' | 'edit' | 'reject'
  comment: string | null
  created_at: string
}

export default function CampaignDetail() {
  const { t, i18n } = useTranslation()
  const { can } = useOrg()
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [missing, setMissing] = useState(false)
  const [personas, setPersonas] = useState<Persona[]>([])
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [pendingGate, setPendingGate] = useState<GateDecision | null>(null)
  const [votes, setVotes] = useState<GateVote[]>([])
  const [required, setRequired] = useState(1)
  const [voters, setVoters] = useState<Record<string, string>>({})
  const { session } = useSession()
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [chatWith, setChatWith] = useState<Persona | null>(null)
  const [alerts, setAlerts] = useState<MarketAlert[]>([])
  const [confirm, setConfirm] = useState<'reject' | 'stop' | null>(null)
  const [category, setCategory] = useState('')
  // The decision engine's recommendations, newest first (re-evaluations add rows).
  const [decisions, setDecisions] = useState<CampaignDecision[]>([])
  // Crash tests before Gate 2, newest first (re-runs add rows).
  const [crashTests, setCrashTests] = useState<CrashTestRow[]>([])
  // Circuit-breaker holds, newest first.
  const [holds, setHolds] = useState<CampaignHold[]>([])
  // The proof-of-impact experiment, if one was declared.
  const [experiment, setExperiment] = useState<Experiment | null>(null)
  // Creative fatigue: the latest analysis, its alerts and the refreshes tried.
  const [fatigue, setFatigue] = useState<{ report: FatigueReport | null; alerts: FatigueAlert[]; interventions: CreativeIntervention[] }>(
    { report: null, alerts: [], interventions: [] })

  usePageLoading(!campaign && !missing)

  const load = useCallback(async () => {
    if (!id) return
    const [{ data: campaignData, error: campaignError }, { data: personaData }, { data: iterationData }, { data: decisionData }, { data: crashData }, { data: holdData }, { data: experimentData }, { data: fatigueReport }, { data: fatigueAlerts }, { data: fatigueRefreshes }] = await Promise.all([
      supabase.from('campaigns').select('*').eq('id', id).maybeSingle(),
      supabase.from('personas').select('*').eq('campaign_id', id),
      supabase.from('iterations').select('*').eq('campaign_id', id).order('round_number').order('preflight_attempt'),
      supabase.from('campaign_decisions').select('*').eq('campaign_id', id).order('created_at', { ascending: false }),
      supabase.from('crash_tests').select('id,round_number,trigger,risk,revised_risk,report,applied_at,created_at').eq('campaign_id', id).order('created_at', { ascending: false }),
      supabase.from('campaign_holds').select('*').eq('campaign_id', id).order('created_at', { ascending: false }),
      supabase.from('experiments').select('*').eq('campaign_id', id).maybeSingle(),
      supabase.from('creative_fatigue_reports').select('*').eq('campaign_id', id).maybeSingle(),
      supabase.from('creative_fatigue_alerts').select('*').eq('campaign_id', id).order('created_at', { ascending: false }),
      supabase.from('creative_interventions').select('*').eq('campaign_id', id).order('created_at', { ascending: false }),
    ])
    // A failed request isn't "not found": say so and offer a retry.
    if (toastLoadError(t, campaignError, () => load())) return
    if (!campaignData) {
      setMissing(true)
      return
    }
    setCampaign(campaignData as Campaign)
    const { data: moments } = await supabase
      .from('market_alerts')
      .select('id,campaign_id,kind,detail,created_at')
      .eq('campaign_id', id)
      .is('dismissed_at', null)
      .order('created_at', { ascending: false })
      .limit(3)
    setAlerts((moments as MarketAlert[] | null) ?? [])
    setPersonas(((personaData as Persona[]) ?? []).sort((a, b) => Number(b.is_primary) - Number(a.is_primary)))
    setIterations((iterationData as Iteration[]) ?? [])
    setDecisions((decisionData as CampaignDecision[]) ?? [])
    setCrashTests((crashData as CrashTestRow[]) ?? [])
    setHolds((holdData as CampaignHold[]) ?? [])
    setExperiment((experimentData as Experiment | null) ?? null)
    setFatigue({ report: (fatigueReport as FatigueReport | null) ?? null, alerts: (fatigueAlerts as FatigueAlert[]) ?? [],
                 interventions: (fatigueRefreshes as CreativeIntervention[]) ?? [] })

    const gateNumber = GATE_NUMBER_BY_STATUS[(campaignData as Campaign).status]
    if (gateNumber) {
      const { data: gateData } = await supabase
        .from('gate_decisions')
        .select('*')
        .eq('campaign_id', id)
        .eq('gate_number', gateNumber)
        .eq('round_number', (campaignData as Campaign).current_round)
        .maybeSingle()
      setPendingGate((gateData as GateDecision) ?? null)
      if (gateData) {
        const orgId = (campaignData as Campaign).org_id
        const [{ data: voteData }, { data: policy }, { data: members }] = await Promise.all([
          supabase.from('gate_approvals').select('user_id,decision,comment,created_at').eq('gate_decision_id', gateData.id),
          supabase.rpc('org_approval_policy', { p_org: orgId }),
          supabase.rpc('org_members', { p_org: orgId }),
        ])
        setVotes((voteData as GateVote[]) ?? [])
        setRequired(Number((policy as { required_approvals?: number } | null)?.required_approvals ?? 1))
        setVoters(Object.fromEntries(((members as { user_id: string; email: string; username: string | null }[] | null) ?? []).map((m) => [m.user_id, m.username || m.email])))
      }
    } else {
      setPendingGate(null)
      setVotes([])
    }
  }, [id, t])

  useEffect(() => {
    load()
  }, [load])

  // Live: the background worker writes status, personas and rounds as it goes.
  useEffect(() => {
    if (!id) return
    const channel = supabase
      .channel(`campaign-${id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaigns', filter: `id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'iterations', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'personas', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'gate_decisions', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'campaign_decisions', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'crash_tests', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaign_holds', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'experiments', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'creative_fatigue_alerts', filter: `campaign_id=eq.${id}` }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [id, load])

  // A destructive button needs a second click within 3s.
  useEffect(() => {
    if (!confirm) return
    const timer = setTimeout(() => setConfirm(null), 3000)
    return () => clearTimeout(timer)
  }, [confirm])

  // Dismissing hides an alert for everyone on the campaign (it's the same signal for all).
  async function dismissAlert(alertId: number) {
    setAlerts((list) => list.filter((a) => a.id !== alertId))
    const { error } = await supabase.from('market_alerts').update({ dismissed_at: new Date().toISOString() }).eq('id', alertId)
    toastFailure(t, error)
  }

  async function resumeNow() {
    // Best-effort: the scheduled sweep is the reliability backstop if this fails.
    try {
      await supabase.functions.invoke('resume-campaign', { body: { campaign_id: id } })
    } catch {
      // no-op: cron will pick it up
    }
  }

  async function submitDecision(decision: 'approve' | 'edit' | 'reject') {
    if (!pendingGate) return
    if (decision === 'reject' && confirm !== 'reject') {
      setConfirm('reject')
      return
    }
    setConfirm(null)
    setSubmitting(true)
    // Gate 1 category correction: update the campaign (the graph re-reads it after
    // the gate, so the bandit uses it) and record a human-verified label for retraining.
    const predicted = campaign?.domain_category
    const corrected = pendingGate.gate_number === 1 && decision !== 'reject' && category && predicted && category !== predicted
    if (corrected && campaign) {
      const { error: categoryError } = await supabase.from('campaigns').update({ domain_category: category }).eq('id', campaign.id)
      if (toastFailure(t, categoryError)) {
        setSubmitting(false)
        return
      }
      const { error: correctionError } = await supabase.from('domain_corrections').insert({
        campaign_id: campaign.id,
        idea: campaign.idea,
        predicted_domain: predicted,
        corrected_domain: category,
      })
      // Never block the gate on the training log (e.g. the domain_corrections migration not applied yet).
      if (correctionError) console.warn('domain correction not recorded:', correctionError.message)
      if (decision === 'approve') decision = 'edit'
    }
    // A vote, not the decision: the database decides the gate once the
    // organisation's required approvals are in (any reject rejects it).
    const { error: voteError } = await supabase
      .from('gate_approvals')
      .insert({ gate_decision_id: pendingGate.id, decision, comment: comment || null })
    if (voteError) {
      setSubmitting(false)
      toastFailure(t, voteError)
      return
    }
    await resumeNow()
    setSubmitting(false)
    setComment('')
    toast.success(t('cd.decisionSent'))
    await load()
  }

  async function stopCampaign() {
    if (!id) return
    if (confirm !== 'stop') {
      setConfirm('stop')
      return
    }
    setConfirm(null)
    setStopping(true)
    const { error } = await supabase.from('campaigns').update({ stop_requested: true }).eq('id', id)
    if (!toastFailure(t, error)) {
      await resumeNow()
      toast.success(t('cd.stopRequested'))
    }
    setStopping(false)
    await load()
  }

  async function setPrimaryPersona(personaId: string) {
    if (!id) return
    // Optimistic: reorder immediately, then persist.
    setPersonas((prev) =>
      prev.map((p) => ({ ...p, is_primary: p.id === personaId })).sort((a, b) => Number(b.is_primary) - Number(a.is_primary)),
    )
    const { error: clearError } = await supabase.from('personas').update({ is_primary: false }).eq('campaign_id', id)
    const { error } = clearError ? { error: clearError } : await supabase.from('personas').update({ is_primary: true }).eq('id', personaId)
    // On failure the reload puts the real order back.
    toastFailure(t, error)
    await load()
  }

  // Latest attempt per round only (earlier pre-flight retries are history).
  const rounds = useMemo(() => {
    const byRound = new Map<number, Iteration>()
    for (const it of iterations) byRound.set(it.round_number, it)
    return [...byRound.values()].sort((a, b) => b.round_number - a.round_number)
  }, [iterations])

  if (missing) {
    return (
      <div className={styles.page}>
        <div className={`${styles.panel} ${styles.empty}`}>
          <h3>{t('cd.notFound')}</h3>
          <Link to="/dashboard" className={`${styles.btn} ${styles.primary}`}>
            {t('cd.back')}
          </Link>
        </div>
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className={styles.page}>
        <span className={styles.skeleton} style={{ height: 16, width: 140 }} />
        <span className={styles.skeleton} style={{ height: 40, width: '60%' }} />
        <span className={styles.skeleton} style={{ height: 88 }} />
        <div className={styles.grid2}>
          <span className={styles.skeleton} style={{ height: 260 }} />
          <span className={styles.skeleton} style={{ height: 260 }} />
        </div>
      </div>
    )
  }

  const isActive = !['completed', 'rejected', 'blocked'].includes(campaign.status)
  const latestDecision = decisions[0] ?? null
  // Approving against the engine's advice needs a reason (the database enforces it too).
  // The crash test of the round now at Gate 2; its risk is the revision's once that's applied.
  const crashNow = crashTests.find((c) => c.round_number === campaign.current_round) ?? null
  const crashRisk = crashNow ? (crashNow.applied_at && crashNow.revised_risk ? crashNow.revised_risk : crashNow.risk) : null
  const crashCritical = pendingGate?.gate_number === 2 && crashRisk === 'critical'
  const decisionAgainst =
    pendingGate?.gate_number === 1 && !!latestDecision && !latestDecision.hard_blocks.length &&
    ['KILL', 'WAIT', 'INSUFFICIENT_EVIDENCE'].includes(latestDecision.decision)
  const needsReason = decisionAgainst || crashCritical
  const reasonMissing = needsReason && comment.trim().length < 10
  const step = currentStep(campaign.status)
  const lang = CAMPAIGN_LANGUAGES.find((l) => l.code === campaign.target_language)
  const gateOpen = pendingGate && !pendingGate.decided_at
  // The database enforces these; the UI only hides what the role can't do.
  const canApprove = can('approve', campaign?.org_id)
  const canCreate = can('create', campaign?.org_id)
  const canManage = can('manage', campaign?.org_id)
  const alreadyVoted = votes.some((v) => v.user_id === session?.user.id)
  const created = new Date(campaign.created_at).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' })
  const summaryEntries = campaign.campaign_summary
    ? Object.entries(campaign.campaign_summary).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v))
    : []

  return (
    <div className={styles.page}>
      <div className={`${styles.crumbs} ${styles.enter}`}>
        <Link to="/dashboard" className={`${styles.back} link-wipe`}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('cd.back')}
        </Link>
        <span className={local.live}>
          {t('dash.live')}
        </span>
      </div>

      <header className={`${styles.header} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
        <div>
          <span className={styles.eyebrow}>{humanize(campaign.domain_category)}</span>
          <h1 className={styles.title}>{campaign.idea}</h1>
          <div className={styles.meta}>
            <StatusPill status={campaign.status} paused={!!campaign.paused_at} />
            <span className={styles.metaChip}>
              {campaign.max_rounds
                ? t('campaignDetail.roundOf', { current: campaign.current_round, max: campaign.max_rounds })
                : t('campaignDetail.round', { current: campaign.current_round })}
            </span>
            {lang && <span className={styles.metaChip}>{lang.label}</span>}
            {campaign.ab_decision && (
              <span className={`${styles.metaChip} ${local.abDecided}`} title={t('ab.decidedExplain', { round: campaign.ab_decision.round })}>
                {t('ab.decidedChip', { variant: campaign.ab_decision.winner.toUpperCase(), pct: Math.round(Math.max(campaign.ab_decision.prob_b_beats_a, 1 - campaign.ab_decision.prob_b_beats_a) * 100) })}
              </span>
            )}
            <span className={styles.metaChip}>{t('cd.created', { time: created })}</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          <Link to={`/campaigns/${id}/metrics`} className={`${styles.btn} ${styles.ghost}`}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 19V5M4 19h16M8 15l4-4 3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('cd.metrics')}
          </Link>
          {isActive && canCreate && (
            <button
              type="button"
              onClick={stopCampaign}
              disabled={stopping || campaign.stop_requested}
              className={`${styles.btn} ${confirm === 'stop' ? styles.dangerSolid : styles.danger}`}
            >
              {campaign.stop_requested || stopping ? t('cd.stopping') : confirm === 'stop' ? t('cd.stopConfirm') : t('cd.stop')}
            </button>
          )}
        </div>
      </header>

      <PausedPanel campaign={campaign} holds={holds} canResume={canManage} onDone={load} />

      {gateOpen && (
        <section className={`${styles.panel} ${local.gate} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties} aria-live="polite">
          <div className={local.gateHead}>
            <span className={local.gateBadge}>{pendingGate.gate_number}</span>
            <div>
              <h2>{t('campaignDetail.gateTitle', { number: pendingGate.gate_number })}</h2>
              <p className={styles.panelSub}>{pendingGate.gate_number === 1 ? t('cd.gate1Body') : t('cd.gate2Body')}</p>
            </div>
          </div>
          {pendingGate.gate_number === 2 && rounds[0] && (
            <div className={local.gateAd}>
              <RoundImage key={`${rounds[0].id}-${rounds[0].image_version ?? 0}`} seedFrom={rounds[0].id} prompt={rounds[0].image_prompt} path={rounds[0].image_path} version={rounds[0].image_version ?? 0} />
              <div className={local.gateAdInfo}>
                <h3>{t('cd.postedNote')}</h3>
                <dl>
                  {rounds[0].headline && (<><dt>{t('cd.adHeadline')}</dt><dd>{rounds[0].headline}</dd></>)}
                  {rounds[0].cta && (<><dt>{t('cd.adButton')}</dt><dd>{rounds[0].cta}</dd></>)}
                  {rounds[0].image_style && (<><dt>{t('cd.adLayout')}</dt><dd>{humanize(rounds[0].image_style)}</dd></>)}
                  {rounds[0].template && (<><dt>{t('product.template')}</dt><dd>{humanize(rounds[0].template)}</dd></>)}
                </dl>
                {canApprove && !alreadyVoted && rounds[0].image_path && (
                  <NewPicture campaignId={campaign.id} round={rounds[0].round_number} version={rounds[0].image_version ?? 0} onDone={load} />
                )}
              </div>
            </div>
          )}
          {pendingGate.gate_number === 2 && campaign.email_audience_frozen_at && (
            <EmailAudience campaign={campaign} editable={false} gate2={canApprove || canCreate} />
          )}
          {pendingGate.gate_number === 2 && <ComplianceRadar flags={rounds[0]?.guardrail_flags ?? null} alwaysShow />}
          {pendingGate.gate_number === 2 && rounds[0]?.focus_group && <FocusGroup result={rounds[0].focus_group} />}
          {pendingGate.gate_number === 2 && crashNow && (
            <CrashTestReport test={crashNow} campaignId={campaign.id} round={campaign.current_round} canAct={canApprove && !alreadyVoted} onChanged={load} />
          )}
          {crashCritical && (
            <div className={local.override} role="note">
              <strong>{t('crash.overrideTitle')}</strong>
              <span>{t('crash.overrideHint')}</span>
            </div>
          )}
          {pendingGate.gate_number === 2 && canApprove && !alreadyVoted && rounds[0]?.copy_text && (
            <CopyEditor campaignId={campaign.id} round={rounds[0].round_number} variant="a" text={rounds[0].copy_text} people={voters} onSaved={load} />
          )}
          {pendingGate.gate_number === 2 && canApprove && !alreadyVoted && rounds[0]?.copy_text_b && (
            <CopyEditor campaignId={campaign.id} round={rounds[0].round_number} variant="b" text={rounds[0].copy_text_b} people={voters} onSaved={load} />
          )}
          {pendingGate.gate_number === 1 && latestDecision && <DecisionCard decision={latestDecision} history={decisions} />}
          {decisionAgainst && (
            <div className={local.override} role="note">
              <strong>{t('decision.overrideTitle', { decision: t(`decision.outcome.${latestDecision!.decision}`) })}</strong>
              <span>{t('decision.overrideHint')}</span>
            </div>
          )}
          {pendingGate.gate_number === 1 && <EmailAudience campaign={campaign} editable={canCreate && !alreadyVoted} onChanged={load} />}
          {pendingGate.gate_number === 1 && (
            <label className={styles.field}>
              <span>{t('cd.categoryLabel')}</span>
              <Select
                className={local.categorySelect}
                aria-label={t('cd.categoryLabel')}
                value={category || campaign.domain_category}
                onChange={setCategory}
                options={DOMAINS.map((d) => ({ value: d, text: humanize(d), label: `${humanize(d)}${d === campaign.domain_category ? ' ✓' : ''}` }))}
              />
              <small className={local.hint}>{t('cd.categoryHint')}</small>
            </label>
          )}
          <label className={styles.field}>
            <span>{needsReason ? t('decision.overrideLabel') : t('cd.commentLabel')}</span>
            <textarea
              className={styles.textarea}
              rows={2}
              placeholder={t('campaignDetail.commentPlaceholder')}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          {!canApprove && <p className={local.hint}>{t('org.cantApprove')}</p>}
          {(required > 1 || votes.length > 0) && (
            <div className={local.votes}>
              <strong>{t('approvals.progress', { count: votes.filter((v) => v.decision !== 'reject').length, required })}</strong>
              <ul>
                {votes.map((v) => (
                  <li key={v.user_id}>
                    <span className={local.voteWho}>{voters[v.user_id] ?? v.user_id.slice(0, 8)}</span>
                    <span className={styles.chip}>{t(`approvals.${v.decision}`)}</span>
                    {v.comment && <q>{v.comment}</q>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className={local.gateActions}>
            <button type="button" disabled={submitting || !canApprove || alreadyVoted || reasonMissing} onClick={() => submitDecision('approve')} className={`${styles.btn} ${styles.primary}`}>
              {submitting && <span className={styles.spinner} aria-hidden="true" />}
              {t('campaignDetail.approve')}
            </button>
            <button type="button" disabled={submitting || !canApprove || alreadyVoted || reasonMissing} onClick={() => submitDecision('edit')} className={`${styles.btn} ${styles.ghost}`}>
              {t('campaignDetail.approveEdits')}
            </button>
            <button
              type="button"
              disabled={submitting || !canApprove || alreadyVoted}
              onClick={() => submitDecision('reject')}
              className={`${styles.btn} ${confirm === 'reject' ? styles.dangerSolid : styles.danger}`}
            >
              {confirm === 'reject' ? t('cd.rejectConfirm') : t('campaignDetail.reject')}
            </button>
          </div>
          <p className={local.hint}>{t('campaignDetail.editHint')}</p>
        </section>
      )}

      {campaign.status === 'blocked' && latestDecision && (
        <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties} aria-live="polite">
          <div className={styles.panelHead}>
            <h2>{t('decision.blockedTitle')}</h2>
          </div>
          <DecisionCard decision={latestDecision} history={decisions} />
        </section>
      )}

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('cd.progressTitle')}</h2>
        </div>
        <ol className={`${local.stepper} ${campaign.status === 'rejected' || campaign.status === 'blocked' ? local.stepperRejected : ''}`}>
          {STEPS.map((s, i) => {
            const state = step === -1 ? '' : i < step ? local.done : i === step ? local.current : ''
            return (
              <li key={s} className={state} style={{ '--i': i } as CSSProperties}>
                <span className={local.stepDot} aria-hidden="true">
                  {i < step ? (
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </span>
                <span className={local.stepLabel}>{t(`cd.${s}`)}</span>
              </li>
            )
          })}
        </ol>
        {campaign.email_audience_frozen_at && <div className={local.audience}><EmailAudience campaign={campaign} editable={false} /></div>}
      </section>

      {/* Feasibility first (it's scored before personas), as one wide card. */}
      <section className={`${styles.panel} ${local.feasPanel} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
        <ScoreRing score={campaign.feasibility_score} />
        <div className={local.feasText}>
          <h2>{t('campaignDetail.feasibilityTitle')}</h2>
          <p className={`${styles.muted} ${local.rationale}`}>{campaign.feasibility_rationale || t('cd.noRationale')}</p>
        </div>
      </section>

      {latestDecision && !(gateOpen && pendingGate?.gate_number === 1) && campaign.status !== 'blocked' && (
        <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
          <DecisionCard decision={latestDecision} history={decisions} />
        </section>
      )}

      <MarketMoments alerts={alerts} onDismiss={dismissAlert} />

      {chatWith && <PersonaChat target={{ kind: 'persona', id: chatWith.id }} persona={chatWith} onClose={() => setChatWith(null)} />}

      {/* Personas side by side: each figure stands above its own info card. */}
      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('campaignDetail.personasTitle')}</h2>
          <span className={styles.chip}>{personas.length}</span>
        </div>
        {personas.length === 0 ? (
          <p className={styles.muted}>{t('cd.noPersonas')}</p>
        ) : (
          <div className={local.personas}>
            {personas.map((p) => (
              <div key={p.id} className={local.personaCol}>
                <PersonaStage archetype={p.archetype} gender={p.gender} name={p.name} demographics={p.demographics} psychographics={p.psychographics} />
                <article className={`${local.persona} ${p.is_primary ? local.personaPrimary : ''}`}>
                  <span className={local.role}>{t(`persona.${archetypeFor(p.archetype, p.name, p.demographics)}`)}</span>
                  <div className={local.personaName}>
                    <strong>{p.name}</strong>
                    {p.is_primary ? (
                      <span className={local.primaryBadge}>{t('campaignDetail.primaryBadge')}</span>
                    ) : canApprove && (
                      <button type="button" className={`${local.makePrimary} link-wipe`} onClick={() => setPrimaryPersona(p.id)}>
                        {t('campaignDetail.makePrimary')}
                      </button>
                    )}
                  </div>
                  <p>{p.demographics}</p>
                  <p>{p.psychographics}</p>
                  <dl className={local.personaMeta}>
                    <div>
                      <dt>{t('cd.channel')}</dt>
                      <dd>{p.channel_fit}</dd>
                    </div>
                    <div>
                      <dt>{t('cd.angle')}</dt>
                      <dd>{p.messaging_angle}</dd>
                    </div>
                  </dl>
                  <button type="button" className={local.interview} onClick={() => setChatWith(p)}>
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><path d="M8 10h8M8 13h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
                    {t('chat.open', { name: p.name.split(/[\s,;:]+/)[0] })}
                  </button>
                </article>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 6 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('campaignDetail.roundsTitle')}</h2>
        </div>
        {rounds.length === 0 ? (
          <p className={styles.muted}>{t('cd.noRounds')}</p>
        ) : (
          <ol className={local.rounds}>
            {rounds.map((it, i) => {
              const bsky = it.bluesky_post_uri ? blueskyUrl(it.bluesky_post_uri) : null
              const published = it.bluesky_post_uri || it.mastodon_post_url || it.reddit_post_url || it.email_id
              return (
                <li key={it.id} className={local.round} style={{ '--i': i } as CSSProperties}>
                  <div className={local.roundRail}>
                    <span className={local.roundNum}>R{it.round_number}</span>
                  </div>
                  <div className={local.roundBody}>
                    <div className={local.roundTop}>
                      <strong>{t('cd.round', { round: it.round_number })}</strong>
                      <span className={styles.chip}>{t('cd.attempt', { attempt: it.preflight_attempt })}</span>
                      {it.image_style && it.copy_tone && (
                        <span className={styles.chip} title={t('cd.arm')}>
                          {humanize(it.image_style)} × {it.copy_tone.replace(/_/g, ' ')}
                        </span>
                      )}
                      {(() => {
                        const ct = crashTests.find((c) => c.round_number === it.round_number)
                        if (!ct) return null
                        const r = ct.applied_at && ct.revised_risk ? ct.revised_risk : ct.risk
                        return <span className={styles.chip}>{t('crash.chip', { risk: t(`crash.risk.${r}`) })}</span>
                      })()}
                    </div>
                    <div className={local.creative}>
                      <RoundImage key={`${it.id}-${it.image_version ?? 0}`} seedFrom={it.id} prompt={it.image_prompt} path={it.image_path} version={it.image_version ?? 0} />
                      <div className={local.creativeText}>
                        {it.copy_text && <blockquote className={local.copy}>{it.copy_text}</blockquote>}
                        {it.copy_text_b && (
                          <>
                            <span className={styles.chip}>{t('ab.variantB')}{it.image_style_b && it.copy_tone_b ? ` · ${humanize(it.image_style_b)} × ${it.copy_tone_b.replace(/_/g, ' ')}` : ''}</span>
                            <blockquote className={local.copy}>{it.copy_text_b}</blockquote>
                          </>
                        )}
                        {!gateOpen && <ComplianceRadar flags={it.guardrail_flags} />}
                        {it.image_prompt && (
                          <p className={local.prompt}>
                            <span>{t('cd.imagePrompt')}</span>
                            {it.image_prompt}
                          </p>
                        )}
                        <div className={local.preflight}>
                          <span>{t('cd.preflight')}</span>
                          <div className={styles.track}>
                            <span className={styles.fill} style={{ width: `${it.preflight_score ?? 0}%` }} />
                          </div>
                          <b>{it.preflight_score ?? '—'}</b>
                          <span className={it.preflight_passed ? local.pass : local.fail}>{it.preflight_passed ? '✓' : '✕'}</span>
                        </div>
                        <div className={local.channels}>
                          <span>{t('cd.publishedTo')}</span>
                          {!published && <em>{t('cd.notPublished')}</em>}
                          {it.bluesky_post_uri &&
                            (bsky ? (
                              <a className={`${styles.chip} ${styles.chipOk}`} href={bsky} target="_blank" rel="noopener noreferrer">
                                Bluesky ↗
                              </a>
                            ) : (
                              <span className={`${styles.chip} ${styles.chipOk}`}>Bluesky</span>
                            ))}
                          {it.mastodon_post_url &&
                            (/^https:\/\//.test(it.mastodon_post_url) ? (
                              <a className={`${styles.chip} ${styles.chipOk}`} href={it.mastodon_post_url} target="_blank" rel="noopener noreferrer">
                                Mastodon ↗
                              </a>
                            ) : (
                              <span className={`${styles.chip} ${styles.chipOk}`}>Mastodon</span>
                            ))}
                          {it.reddit_post_url && (
                            <a className={`${styles.chip} ${styles.chipOk}`} href={it.reddit_post_url} target="_blank" rel="noopener noreferrer">
                              Reddit ↗
                            </a>
                          )}
                          {it.email_id && <span className={`${styles.chip} ${styles.chipOk}`}>Email</span>}
                        </div>
                        {!gateOpen && it.focus_group && <FocusGroup result={it.focus_group} compact />}
                        {it.arm_explain && <ArmExplain explain={it.arm_explain} />}
                      </div>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </section>

      <ProofOfImpact
        campaign={campaign}
        experiment={experiment}
        canEdit={canCreate || canManage}
        emailSent={iterations.some((it) => !!it.email_id && !/^(DRY_RUN|skipped|failed:|dead:|held:)/.test(it.email_id))}
        onDone={load}
      />

      <CreativeFatigue report={fatigue.report} alerts={fatigue.alerts} interventions={fatigue.interventions}
        canEdit={isActive && (canCreate || canManage)} onDone={load} />

      {(isActive || holds.length > 0) && (
        <SafetyControls
          key={campaign.offer_ends_at ?? 'none'}
          campaign={campaign}
          holds={holds}
          canStop={isActive && canApprove}
          canEdit={isActive && (canCreate || canManage)}
          onDone={load}
        />
      )}

      {campaign.status === 'completed' && campaign.campaign_summary && (
        <section className={`${styles.panel} ${local.summary} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('campaignDetail.summaryTitle')}</h2>
          </div>
          {summaryEntries.length > 0 && (
            <dl className={local.summaryGrid}>
              {summaryEntries.map(([k, v]) => (
                <div key={k}>
                  <dt>{humanize(k)}</dt>
                  <dd>{typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v)}</dd>
                </div>
              ))}
            </dl>
          )}
          <details className={styles.details}>
            <summary>{t('cd.rawData')}</summary>
            <pre className={styles.code}>{JSON.stringify(campaign.campaign_summary, null, 2)}</pre>
          </details>
        </section>
      )}
      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 8 } as CSSProperties}>
        <div className={styles.panelHead}>
          <div>
            <h2>{t('collab.title')}</h2>
            <p className={styles.panelSub}>{t('collab.sub')}</p>
          </div>
        </div>
        <CampaignComments campaignId={campaign.id} orgId={campaign.org_id} rounds={rounds.map((r) => r.round_number).sort((a, b) => a - b)} />
      </section>
    </div>
  )
}
