import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import LogoMark from '../components/LogoMark'
import RewardChart, { type RewardPoint } from '../components/RewardChart'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import Onboarding from '../components/Onboarding'
import { useOrg } from '../lib/useOrg'
import { supabase } from '../lib/supabaseClient'
import { displayName } from '../lib/profile'
import { useSession } from '../lib/useAuth'
import type { Campaign, CampaignStatus, Metric } from '../lib/types'
import styles from './Dashboard.module.css'
import Select from '../components/Select'

// Only the iteration fields the dashboard needs (arm per round).
interface IterationArm {
  campaign_id: string
  round_number: number
  preflight_attempt: number
  image_style: string | null
  copy_tone: string | null
}

type Filter = 'all' | 'action' | 'running' | 'done'

const STATUS_ORDER: CampaignStatus[] = [
  'created',
  'awaiting_gate_1',
  'awaiting_gate_2',
  'awaiting_metrics',
  'awaiting_next_round',
  'completed',
  'rejected',
]
const NEEDS_ACTION: CampaignStatus[] = ['awaiting_gate_1', 'awaiting_gate_2']
const RUNNING: CampaignStatus[] = ['created', 'awaiting_metrics', 'awaiting_next_round']
const DONE: CampaignStatus[] = ['completed', 'rejected']
const FILTER_STATUSES: Record<Filter, CampaignStatus[] | null> = {
  all: null,
  action: NEEDS_ACTION,
  running: RUNNING,
  done: DONE,
}
const FREE_ROUNDS = 3
const PAID_ROUNDS = 10

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Engagement = every counted interaction; "recipients" is a denominator, not engagement. */
function engagementOf(m: Metric) {
  return Object.entries(m.raw_metrics).reduce((sum, [k, v]) => (k === 'recipients' ? sum : sum + (Number(v) || 0)), 0)
}

function prefersReducedMotion() {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

/** Animates a number from 0 to `target` once `enabled` turns true. */
function useCountUp(target: number, enabled: boolean, decimals = 0) {
  const [value, setValue] = useState(0)
  useEffect(() => {
    if (!enabled) return
    if (prefersReducedMotion()) {
      setValue(target)
      return
    }
    let raf = 0
    const start = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / 900)
      setValue(target * (1 - Math.pow(1 - p, 3)))
      if (p < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [target, enabled])
  return value.toFixed(decimals)
}

function useRelativeTime() {
  const { i18n } = useTranslation()
  return useMemo(() => {
    const rtf = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' })
    const units: [Intl.RelativeTimeFormatUnit, number][] = [
      ['year', 31536000],
      ['month', 2592000],
      ['week', 604800],
      ['day', 86400],
      ['hour', 3600],
      ['minute', 60],
    ]
    return (iso: string) => {
      const diff = (new Date(iso).getTime() - Date.now()) / 1000
      for (const [unit, secs] of units) {
        if (Math.abs(diff) >= secs) return rtf.format(Math.round(diff / secs), unit)
      }
      return rtf.format(0, 'minute')
    }
  }, [i18n.language])
}

/* ------------------------------------------------------------------ */
/* Small presentational pieces                                         */
/* ------------------------------------------------------------------ */

function Kpi({
  label,
  value,
  hint,
  index,
  children,
}: {
  label: string
  value: string
  hint: string
  index: number
  children?: ReactNode
}) {
  return (
    <div className={`${styles.panel} ${styles.kpi} ${styles.enter}`} style={{ '--i': index } as CSSProperties}>
      <span className={styles.kpiLabel}>{label}</span>
      <div className={styles.kpiRow}>
        <span className={styles.kpiValue}>{value}</span>
        {children}
      </div>
      <span className={styles.kpiHint}>{hint}</span>
    </div>
  )
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null
  const w = 96
  const h = 32
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - 3 - v * (h - 6)}`).join(' ')
  return (
    <svg className={styles.spark} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline points={pts} fill="none" stroke="var(--mos-accent)" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

/** Single-hue horizontal bars; labels and values stay in text ink. */
function BarList({
  rows,
  max,
  format,
  onSelect,
}: {
  rows: { key: string; label: string; value: number; note?: string }[]
  max: number
  format: (v: number) => string
  onSelect?: (key: string) => void
}) {
  return (
    <ul className={styles.barList}>
      {rows.map((r, i) => {
        const content = (
          <>
            <div className={styles.barTop}>
              <span className={styles.barLabel}>{r.label}</span>
              <span className={styles.barValue}>
                {format(r.value)}
                {r.note && <small>{r.note}</small>}
              </span>
            </div>
            <div className={styles.barTrack}>
              <span
                className={styles.barFill}
                style={{ '--w': `${max > 0 ? (r.value / max) * 100 : 0}%`, '--i': i } as CSSProperties}
              />
            </div>
          </>
        )
        return (
          <li key={r.key} className={r.value === 0 ? styles.barZero : ''} title={`${r.label}: ${format(r.value)}`}>
            {onSelect ? (
              <button type="button" className={styles.barButton} onClick={() => onSelect(r.key)}>
                {content}
              </button>
            ) : (
              content
            )}
          </li>
        )
      })}
    </ul>
  )
}

function StatusPill({ status }: { status: CampaignStatus }) {
  const { t } = useTranslation()
  const tone = NEEDS_ACTION.includes(status)
    ? styles.pillAction
    : status === 'completed'
      ? styles.pillDone
      : status === 'rejected'
        ? styles.pillRejected
        : styles.pillRunning
  return (
    <span className={`${styles.pill} ${tone}`}>
      <span className={styles.pillDot} aria-hidden="true" />
      {t(`dash.st_${status}`)}
    </span>
  )
}

function Skeleton({ h, w = '100%' }: { h: number; w?: string }) {
  return <span className={styles.skeleton} style={{ height: h, width: w }} aria-hidden="true" />
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

interface OrgUsage {
  plan: 'free' | 'pro' | 'enterprise'
  limits: Record<'campaigns_per_day' | 'active_campaigns' | 'members' | 'llm_tokens_per_day', number | null>
  used: Record<'campaigns_per_day' | 'active_campaigns' | 'members' | 'llm_tokens_per_day', number>
}

/** The active organisation's usage against its plan (limits enforced by the database). */
function UsageMeters({ usage }: { usage: OrgUsage }) {
  const { t } = useTranslation()
  const rows = (['campaigns_per_day', 'active_campaigns', 'llm_tokens_per_day'] as const).filter((k) => usage.limits[k] != null)
  if (!rows.length) return <p className={styles.planRounds}>{t('usage.unlimited', { plan: usage.plan })}</p>
  return (
    <ul className={styles.usage}>
      {rows.map((k) => {
        const limit = usage.limits[k] as number
        const used = usage.used[k]
        const pct = Math.min(100, Math.round((used / limit) * 100))
        return (
          <li key={k}>
            <div className={styles.usageHead}>
              <span>{t(`usage.${k}`)}</span>
              <span>{k === 'llm_tokens_per_day' ? `${pct}%` : `${used} / ${limit}`}</span>
            </div>
            <div className={styles.usageTrack} role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={t(`usage.${k}`)}>
              <span className={pct >= 100 ? styles.usageFull : ''} style={{ width: `${pct}%` }} />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default function Dashboard() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { session } = useSession()
  const relTime = useRelativeTime()
  const composerRef = useRef<HTMLTextAreaElement>(null)

  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [arms, setArms] = useState<IterationArm[]>([])
  const [tier, setTier] = useState<'free' | 'subscribed'>('free')
  const [usage, setUsage] = useState<OrgUsage | null>(null)
  const [firstLoad, setFirstLoad] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const [idea, setIdea] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('en')
  const [abTest, setAbTest] = useState(false)
  const [creating, setCreating] = useState(false)
  const [toast, setToast] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const [filter, setFilter] = useState<Filter>('all')
  const { active: org, can } = useOrg()
  const orgId = org?.id
  const canCreate = can('create')
  const [query, setQuery] = useState('')

  // Quiet reload: after the first load, data swaps in place without skeletons.
  const load = useCallback(async () => {
    if (!orgId) return
    const [c, m, it, sub] = await Promise.all([
      supabase.from('campaigns').select('*').eq('org_id', orgId).order('created_at', { ascending: false }),
      supabase.from('metrics').select('*').order('collected_at', { ascending: true }),
      supabase.from('iterations').select('campaign_id,round_number,preflight_attempt,image_style,copy_tone'),
      supabase.from('subscriptions').select('status').maybeSingle(),
    ])
    // RLS returns every organisation the user belongs to; show the active one.
    const inOrg = new Set(((c.data as Campaign[]) ?? []).map((x) => x.id))
    setCampaigns((c.data as Campaign[]) ?? [])
    setMetrics(((m.data as Metric[]) ?? []).filter((x) => inOrg.has(x.campaign_id)))
    setArms(((it.data as IterationArm[]) ?? []).filter((x) => inOrg.has(x.campaign_id)))
    setTier(sub.data?.status === 'subscribed' ? 'subscribed' : 'free')
    const { data: u } = await supabase.rpc('org_usage', { p_org: orgId })
    setUsage((u as OrgUsage | null) ?? null)
    setFirstLoad(false)
  }, [orgId])

  useEffect(() => {
    load()
  }, [load])

  // Live updates: any change to this user's campaigns or metrics (RLS-scoped)
  // triggers a quiet reload.
  useEffect(() => {
    const channel = supabase
      .channel('dashboard-live')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaigns' }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'metrics' }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [load])

  // Toasts clear themselves.
  useEffect(() => {
    if (!toast) return
    const id = setTimeout(() => setToast(null), toast.kind === 'ok' ? 8000 : 12000)
    return () => clearTimeout(id)
  }, [toast])

  async function refresh() {
    setRefreshing(true)
    await load()
    setRefreshing(false)
  }

  async function createCampaign() {
    if (!idea.trim() || creating || !canCreate) return
    setCreating(true)
    setToast(null)
    const { error, response } = await supabase.functions.invoke('create-campaign', {
      body: { idea: idea.trim(), target_language: targetLanguage, org_id: orgId, ab_test: abTest },
    })
    setCreating(false)
    if (error) {
      // Plan limits come back as 429 with the reason in the body.
      let message = error.message
      if (response?.status === 429) {
        message = ((await response.json().catch(() => null)) as { error?: string } | null)?.error ?? message
      }
      setToast({ kind: 'error', text: t('dash.dispatchFailed', { message }) })
      return
    }
    setToast({ kind: 'ok', text: t('dash.dispatched') })
    setIdea('')
  }

  function onComposerKey(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      createCampaign()
    }
  }

  function focusComposer() {
    composerRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    composerRef.current?.focus({ preventScroll: true })
  }

  /* ---------- derived data ---------- */
  const byId = useMemo(() => new Map(campaigns.map((c) => [c.id, c])), [campaigns])

  // One reward per (campaign, round): the mean across that round's channels.
  const roundRewards = useMemo(() => {
    const groups = new Map<string, { campaign_id: string; round: number; rewards: number[]; at: string }>()
    for (const m of metrics) {
      const key = `${m.campaign_id}:${m.round_number}`
      const g = groups.get(key) ?? { campaign_id: m.campaign_id, round: m.round_number, rewards: [], at: m.collected_at }
      g.rewards.push(m.reward)
      if (m.collected_at > g.at) g.at = m.collected_at
      groups.set(key, g)
    }
    return [...groups.entries()]
      .map(([key, g]) => ({ key, ...g, reward: g.rewards.reduce((a, b) => a + b, 0) / g.rewards.length }))
      .sort((a, b) => a.at.localeCompare(b.at))
  }, [metrics])

  const trend: RewardPoint[] = roundRewards.map((r) => ({
    key: r.key,
    reward: r.reward,
    label: `R${r.round}`,
    title: t('dash.trendTooltip', { round: r.round, reward: r.reward.toFixed(2) }),
    detail: byId.get(r.campaign_id)?.idea ?? '',
  }))

  const active = campaigns.filter((c) => !DONE.includes(c.status)).length
  const finished = campaigns.length - active
  const scored = campaigns.filter((c) => c.feasibility_score !== null)
  const avgFeasibility = scored.length ? scored.reduce((s, c) => s + (c.feasibility_score ?? 0), 0) / scored.length : 0
  const totalEngagement = metrics.reduce((s, m) => s + engagementOf(m), 0)
  const bestReward = roundRewards.reduce((best, r) => Math.max(best, r.reward), 0)
  const needsYou = campaigns.filter((c) => NEEDS_ACTION.includes(c.status))

  const kpiReady = !firstLoad
  const activeShown = useCountUp(active, kpiReady)
  const feasShown = useCountUp(avgFeasibility, kpiReady)
  const engShown = useCountUp(totalEngagement, kpiReady)
  const rewardShown = useCountUp(bestReward, kpiReady, 2)

  const channelTotals = useMemo(() => {
    const sum = (channel: Metric['channel'], key: string) =>
      metrics.filter((m) => m.channel === channel).reduce((s, m) => s + (Number(m.raw_metrics[key]) || 0), 0)
    return {
      bluesky: { likes: sum('bluesky', 'likes'), reposts: sum('bluesky', 'reposts'), replies: sum('bluesky', 'replies') },
      email: { clicks: sum('email', 'clicks'), recipients: sum('email', 'recipients') },
      hasBluesky: metrics.some((m) => m.channel === 'bluesky'),
      hasEmail: metrics.some((m) => m.channel === 'email'),
    }
  }, [metrics])

  // Arm leaderboard: the final pre-flight attempt of each measured round.
  const armRows = useMemo(() => {
    const finalAttempt = new Map<string, IterationArm>()
    for (const it of arms) {
      const key = `${it.campaign_id}:${it.round_number}`
      const prev = finalAttempt.get(key)
      if (!prev || it.preflight_attempt > prev.preflight_attempt) finalAttempt.set(key, it)
    }
    const perArm = new Map<string, number[]>()
    for (const r of roundRewards) {
      const it = finalAttempt.get(r.key)
      if (!it?.image_style || !it.copy_tone) continue
      const arm = `${humanize(it.image_style)} × ${it.copy_tone.replace(/_/g, ' ')}`
      perArm.set(arm, [...(perArm.get(arm) ?? []), r.reward])
    }
    return [...perArm.entries()]
      .map(([arm, rs]) => ({ key: arm, label: arm, value: rs.reduce((a, b) => a + b, 0) / rs.length, note: `n=${rs.length}` }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 5)
  }, [arms, roundRewards])

  const pipelineRows = STATUS_ORDER.map((s) => ({
    key: s,
    label: t(`dash.st_${s}`),
    value: campaigns.filter((c) => c.status === s).length,
  }))
  const pipelineMax = Math.max(1, ...pipelineRows.map((r) => r.value))

  const activity = useMemo(() => {
    const events = [
      ...campaigns.map((c) => ({ key: `c-${c.id}`, at: c.created_at, id: c.id, kind: 'created' as const, idea: c.idea, round: 0 })),
      ...roundRewards.map((r) => ({
        key: `m-${r.key}`,
        at: r.at,
        id: r.campaign_id,
        kind: 'measured' as const,
        idea: byId.get(r.campaign_id)?.idea ?? '',
        round: r.round,
      })),
    ]
    return events.sort((a, b) => b.at.localeCompare(a.at)).slice(0, 6)
  }, [campaigns, roundRewards, byId])

  const visible = campaigns.filter((c) => {
    const statuses = FILTER_STATUSES[filter]
    if (statuses && !statuses.includes(c.status)) return false
    const q = query.trim().toLowerCase()
    return !q || c.idea.toLowerCase().includes(q) || c.domain_category.toLowerCase().includes(q)
  })
  const counts: Record<Filter, number> = {
    all: campaigns.length,
    action: needsYou.length,
    running: campaigns.filter((c) => RUNNING.includes(c.status)).length,
    done: finished,
  }

  const hour = new Date().getHours()
  const greeting = hour < 12 ? t('dash.greetingMorning') : hour < 18 ? t('dash.greetingAfternoon') : t('dash.greetingEvening')
  // Username (or the name Google/GitHub gave us); never the email address.
  const name = displayName(session?.user)
  const roundsCap = tier === 'subscribed' ? PAID_ROUNDS : FREE_ROUNDS

  function selectPipeline(status: string) {
    const s = status as CampaignStatus
    setFilter(NEEDS_ACTION.includes(s) ? 'action' : DONE.includes(s) ? 'done' : 'running')
    document.getElementById('campaigns')?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <h1 className={styles.title}>
            {greeting}
            {name ? <span className={styles.name}>, {name}</span> : null}
          </h1>
          <p className={styles.subtitle}>
            {t('dash.subtitle')}
            {!name && (
              <>
                {' '}
                <Link to="/settings#account" className={`${styles.addName} link-wipe`}>
                  {t('dash.addUsername')} →
                </Link>
              </>
            )}
          </p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.live}>
            {t('dash.live')}
          </span>
          <button type="button" className={styles.iconBtn} onClick={refresh} aria-label={t('dashboard.refresh')} title={t('dashboard.refresh')}>
            <svg className={refreshing ? styles.spinning : ''} viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <button type="button" className={styles.primaryBtn} onClick={focusComposer}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
            </svg>
            {t('dash.newCampaign')}
          </button>
        </div>
      </header>

      {!firstLoad && <Onboarding campaignCount={campaigns.length} />}

      {/* Needs-your-approval banner */}
      {needsYou.length > 0 && (
        <div className={`${styles.attention} ${styles.enter}`} role="status">
          <span className={styles.attentionIcon} aria-hidden="true">!</span>
          <span className={styles.attentionText}>{t('dash.attention', { count: needsYou.length })}</span>
          <div className={styles.attentionLinks}>
            {needsYou.slice(0, 3).map((c) => (
              <Link key={c.id} to={`/campaigns/${c.id}`} className={styles.attentionLink}>
                {c.idea.length > 34 ? `${c.idea.slice(0, 34)}…` : c.idea}
                <span aria-hidden="true">→</span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {/* KPIs */}
      <section className={styles.kpis}>
        {firstLoad ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className={`${styles.panel} ${styles.kpi}`}>
              <Skeleton h={12} w="45%" />
              <Skeleton h={34} w="35%" />
              <Skeleton h={10} w="60%" />
            </div>
          ))
        ) : (
          <>
            <Kpi index={0} label={t('dash.kpiActive')} value={activeShown} hint={t('dash.kpiActiveHint', { count: finished })} />
            <Kpi
              index={1}
              label={t('dash.kpiFeasibility')}
              value={scored.length ? feasShown : '—'}
              hint={t('dash.kpiFeasibilityHint', { count: scored.length })}
            >
              {scored.length > 0 && (
                <span className={styles.kpiMeter} aria-hidden="true">
                  <span style={{ '--w': `${avgFeasibility}%` } as CSSProperties} />
                </span>
              )}
            </Kpi>
            <Kpi index={2} label={t('dash.kpiEngagement')} value={engShown} hint={t('dash.kpiEngagementHint')} />
            <Kpi index={3} label={t('dash.kpiReward')} value={roundRewards.length ? rewardShown : '—'} hint={t('dash.kpiRewardHint')}>
              <Sparkline values={trend.slice(-12).map((p) => p.reward)} />
            </Kpi>
          </>
        )}
      </section>

      {/* Composer + plan/guide */}
      <section className={styles.gridMain}>
        <div className={`${styles.panel} ${styles.composer} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('dashboard.createTitle')}</h2>
            <kbd className={styles.kbd}>Ctrl ↵</kbd>
          </div>
          <p className={styles.panelSub}>{t('dash.composerHint')}</p>
          <div className={styles.textareaWrap}>
            <textarea
              ref={composerRef}
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              onKeyDown={onComposerKey}
              placeholder={t('dashboard.ideaPlaceholder')}
              rows={3}
              maxLength={500}
              className={styles.textarea}
            />
            <span className={styles.charCount}>{t('dash.chars', { count: idea.length })}</span>
          </div>
          <div className={styles.examples}>
            <span>{t('dash.examples')}</span>
            {(['example1', 'example2', 'example3'] as const).map((k) => (
              <button key={k} type="button" className={styles.chip} onClick={() => setIdea(t(`dash.${k}`))}>
                {t(`dash.${k}`)}
              </button>
            ))}
          </div>
          <div className={styles.composerFoot}>
            <label className={styles.langPick}>
              <span>{t('dashboard.languageLabel')}</span>
              <Select
                aria-label={t('dashboard.languageLabel')}
                value={targetLanguage}
                onChange={setTargetLanguage}
                options={CAMPAIGN_LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
              />
            </label>
            <label className={styles.langPick} title={t('ab.hint')}>
              <input type="checkbox" checked={abTest} onChange={(e) => setAbTest(e.target.checked)} style={{ width: 16, height: 16, accentColor: 'var(--mos-accent)' }} />
              <span>{t('ab.toggle')}</span>
            </label>
            <button type="button" className={styles.primaryBtn} onClick={createCampaign} disabled={creating || !idea.trim() || !canCreate} title={canCreate ? undefined : t('org.cantCreate')}>
              {creating && <span className={styles.spinner} aria-hidden="true" />}
              {creating ? t('dashboard.creating') : t('dashboard.createSubmit')}
              {!creating && (
                <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
          {toast && (
            <p className={`${styles.toast} ${toast.kind === 'ok' ? styles.toastOk : styles.toastError}`} role={toast.kind === 'ok' ? 'status' : 'alert'}>
              {toast.text}
              <button type="button" onClick={() => setToast(null)} aria-label="Dismiss">
                ×
              </button>
            </p>
          )}
        </div>

        <div className={styles.sideStack}>
          <div className={`${styles.panel} ${styles.plan} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
            <div className={styles.panelHead}>
              <h2>{t('dash.planTitle')}</h2>
              <span className={`${styles.tierBadge} ${tier === 'subscribed' ? styles.tierPaid : ''}`}>
                {tier === 'subscribed' ? t('dash.planSubscribed') : t('dash.planFree')}
              </span>
            </div>
            <p className={styles.planRounds}>{t('dash.planRounds', { rounds: roundsCap })}</p>
            {usage && <UsageMeters usage={usage} />}
            <Link to="/settings" className={`${styles.planLink} link-wipe`}>
              {t('dash.planKeys')} →
            </Link>
          </div>

          <div className={`${styles.panel} ${styles.guide} ${styles.enter}`} style={{ '--i': 6 } as CSSProperties}>
            {/* Placeholder until a real walkthrough video exists. */}
            <div className={styles.video}>
              <span className={styles.play} aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8 5.5v13l11-6.5z" />
                </svg>
              </span>
              <span className={styles.videoLabel}>{t('dash.videoPlaceholder')}</span>
            </div>
            <h3>{t('dash.guideTitle')}</h3>
            <p>{t('dash.guideBody')}</p>
          </div>
        </div>
      </section>

      {/* Trend + pipeline */}
      <section className={styles.gridMain}>
        <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
          <div className={styles.panelHead}>
            <div>
              <h2>{t('dash.trendTitle')}</h2>
              <p className={styles.panelSub}>{t('dash.trendSub')}</p>
            </div>
          </div>
          {firstLoad ? (
            <Skeleton h={220} />
          ) : trend.length === 0 ? (
            <div className={styles.emptyChart}>
              <svg viewBox="0 0 120 48" aria-hidden="true">
                <path d="M4 40 L30 30 L52 34 L78 18 L116 10" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 5" strokeLinecap="round" />
              </svg>
              <p>{t('dash.trendEmpty')}</p>
            </div>
          ) : (
            <RewardChart points={trend} ariaLabel={t('dash.trendTitle')} />
          )}
        </div>

        <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 8 } as CSSProperties}>
          <div className={styles.panelHead}>
            <div>
              <h2>{t('dash.pipelineTitle')}</h2>
              <p className={styles.panelSub}>{t('dash.pipelineSub')}</p>
            </div>
          </div>
          {firstLoad ? (
            <div className={styles.skelStack}>
              {[0, 1, 2, 3, 4].map((i) => (
                <Skeleton key={i} h={22} />
              ))}
            </div>
          ) : (
            <BarList rows={pipelineRows} max={pipelineMax} format={(v) => String(v)} onSelect={selectPipeline} />
          )}
        </div>
      </section>

      {/* Campaigns + insights rail */}
      <section className={styles.gridMain}>
        <div className={`${styles.panel} ${styles.tablePanel} ${styles.enter}`} style={{ '--i': 9 } as CSSProperties} id="campaigns">
          <div className={styles.tableHead}>
            <h2>{t('dash.campaignsTitle')}</h2>
            <div className={styles.search}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
                <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('dash.search')} aria-label={t('dash.search')} />
            </div>
          </div>

          <div className={styles.tabs} role="tablist">
            {(['all', 'action', 'running', 'done'] as const).map((f) => (
              <button
                key={f}
                type="button"
                role="tab"
                aria-selected={filter === f}
                className={`${styles.tab} ${filter === f ? styles.tabActive : ''}`}
                onClick={() => setFilter(f)}
              >
                {t(`dash.filter${f[0].toUpperCase()}${f.slice(1)}`)}
                <span className={styles.tabCount}>{counts[f]}</span>
              </button>
            ))}
          </div>

          {firstLoad ? (
            <div className={styles.skelStack}>
              {[0, 1, 2, 3].map((i) => (
                <Skeleton key={i} h={56} />
              ))}
            </div>
          ) : campaigns.length === 0 ? (
            <div className={styles.empty}>
              <div className={styles.emptyArt} aria-hidden="true">
                <LogoMark />
              </div>
              <h3>{t('dash.emptyTitle')}</h3>
              <p>{t('dash.emptyBody')}</p>
              <button type="button" className={styles.primaryBtn} onClick={focusComposer}>
                {t('dash.newCampaign')}
              </button>
            </div>
          ) : visible.length === 0 ? (
            <p className={styles.noMatch}>{t('dash.noMatch')}</p>
          ) : (
            <div className={styles.table} role="table">
              <div className={`${styles.tr} ${styles.th}`} role="row">
                <span role="columnheader">{t('dash.colCampaign')}</span>
                <span role="columnheader">{t('dash.colStatus')}</span>
                <span role="columnheader">{t('dash.colFeasibility')}</span>
                <span role="columnheader">{t('dash.colRound')}</span>
                <span role="columnheader">{t('dash.colCreated')}</span>
              </div>
              {visible.map((c, i) => {
                const lang = CAMPAIGN_LANGUAGES.find((l) => l.code === c.target_language)
                return (
                  <div
                    key={c.id}
                    role="row"
                    tabIndex={0}
                    className={`${styles.tr} ${styles.row}`}
                    style={{ '--i': i } as CSSProperties}
                    onClick={() => navigate(`/campaigns/${c.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') navigate(`/campaigns/${c.id}`)
                    }}
                  >
                    <span role="cell" className={styles.cellIdea}>
                      <strong>{c.idea}</strong>
                      <small>
                        {humanize(c.domain_category)}
                        {lang ? ` · ${lang.label}` : ''}
                      </small>
                    </span>
                    <span role="cell">
                      <StatusPill status={c.status} />
                    </span>
                    <span role="cell" className={styles.cellFeas}>
                      {c.feasibility_score ?? '—'}
                      {c.feasibility_score !== null && (
                        <span className={styles.miniBar} aria-hidden="true">
                          <span style={{ width: `${c.feasibility_score}%` }} />
                        </span>
                      )}
                    </span>
                    <span role="cell" className={styles.mono}>
                      {c.current_round}
                      {c.max_rounds ? ` / ${c.max_rounds}` : ''}
                    </span>
                    <span role="cell" className={styles.cellTime}>
                      {relTime(c.created_at)}
                      <svg className={styles.rowArrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                        <path d="M9 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <aside className={styles.sideStack}>
          <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 10 } as CSSProperties}>
            <div className={styles.panelHead}>
              <h2>{t('dash.channelsTitle')}</h2>
            </div>
            <div className={styles.channels}>
              <div className={styles.channel}>
                <span className={styles.channelIcon} aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M6.3 4.6C8.6 6.3 11 9.8 12 11.8c1-2 3.4-5.5 5.7-7.2 1.7-1.2 4.3-2.1 4.3.8 0 .6-.3 4.9-.5 5.6-.7 2.4-3.2 3.1-5.4 2.7 3.9.7 4.9 2.9 2.8 5-4 4.1-5.8-1-6.2-2.4l-.2-.5-.2.5c-.4 1.4-2.2 6.5-6.2 2.4-2.1-2.1-1.1-4.3 2.8-5-2.2.4-4.7-.3-5.4-2.7C3.3 10.3 3 6 3 5.4c0-2.9 2.6-2 4.3-.8z" />
                  </svg>
                </span>
                <div>
                  <strong>Bluesky</strong>
                  <span>
                    {channelTotals.hasBluesky ? t('dash.blueskyDetail', channelTotals.bluesky) : t('dash.channelEmpty')}
                  </span>
                </div>
                <b className={styles.channelTotal}>
                  {channelTotals.bluesky.likes + channelTotals.bluesky.reposts + channelTotals.bluesky.replies}
                </b>
              </div>
              <div className={styles.channel}>
                <span className={styles.channelIcon} aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none">
                    <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
                    <path d="M3.5 6.5L12 13l8.5-6.5" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                  </svg>
                </span>
                <div>
                  <strong>Email</strong>
                  <span>{channelTotals.hasEmail ? t('dash.emailDetail', channelTotals.email) : t('dash.channelEmpty')}</span>
                </div>
                <b className={styles.channelTotal}>{channelTotals.email.clicks}</b>
              </div>
            </div>
          </div>

          <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 11 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('dash.armsTitle')}</h2>
                <p className={styles.panelSub}>{t('dash.armsSub')}</p>
              </div>
            </div>
            {armRows.length === 0 ? (
              <p className={styles.muted}>{t('dash.armsEmpty')}</p>
            ) : (
              <BarList rows={armRows} max={1} format={(v) => v.toFixed(2)} />
            )}
          </div>

          <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 12 } as CSSProperties}>
            <div className={styles.panelHead}>
              <h2>{t('dash.activityTitle')}</h2>
            </div>
            {activity.length === 0 ? (
              <p className={styles.muted}>{t('dash.activityEmpty')}</p>
            ) : (
              <ol className={styles.activity}>
                {activity.map((e) => (
                  <li key={e.key}>
                    <span className={`${styles.activityDot} ${e.kind === 'measured' ? styles.activityDotAccent : ''}`} aria-hidden="true" />
                    <Link to={`/campaigns/${e.id}`} className={styles.activityText}>
                      {e.kind === 'created'
                        ? t('dash.activityCreated', { idea: e.idea })
                        : t('dash.activityMeasured', { idea: e.idea, round: e.round })}
                    </Link>
                    <time dateTime={e.at}>{relTime(e.at)}</time>
                  </li>
                ))}
              </ol>
            )}
          </div>
        </aside>
      </section>
    </div>
  )
}
