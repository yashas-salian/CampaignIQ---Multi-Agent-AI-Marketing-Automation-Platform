import type { CSSProperties, KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import LogoMark from '../components/LogoMark'
import RewardChart, { type RewardPoint } from '../components/RewardChart'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import Onboarding from '../components/Onboarding'
import MarketMoments, { type MarketAlert } from '../components/MarketMoments'
import { toast } from '../lib/toast'
import { toastFailure, toastLoadError } from '../lib/notify'
import { usePageLoading } from '../lib/loading'
import { useOrg } from '../lib/useOrg'
import { supabase } from '../lib/supabaseClient'
import { displayName } from '../lib/profile'
import { useSession } from '../lib/useAuth'
import type { Campaign, CampaignStatus, Metric } from '../lib/types'
import styles from './Dashboard.module.css'
import Select from '../components/Select'
import { ProductFields } from '../components/ProductFields'
import { isWebLink } from '../lib/product'

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
  const { hash } = useLocation()
  const { session } = useSession()
  const relTime = useRelativeTime()
  const composerRef = useRef<HTMLTextAreaElement>(null)

  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [arms, setArms] = useState<IterationArm[]>([])
  const [loop, setLoop] = useState<{ rounds: number; tried: number } | null>(null)
  const [alerts, setAlerts] = useState<MarketAlert[]>([])
  const [tier, setTier] = useState<'free' | 'subscribed'>('free')
  const [usage, setUsage] = useState<OrgUsage | null>(null)
  const [firstLoad, setFirstLoad] = useState(true)
  usePageLoading(firstLoad)
  const [refreshing, setRefreshing] = useState(false)

  const [idea, setIdea] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('en')
  const [abTest, setAbTest] = useState(false)
  const [productPhoto, setProductPhoto] = useState<File | null>(null)
  const [tagline, setTagline] = useState('')
  const [ctaLink, setCtaLink] = useState('')
  const [creating, setCreating] = useState(false)

  const [filter, setFilter] = useState<Filter>('all')
  const { active: org, can } = useOrg()
  const orgId = org?.id
  const canCreate = can('create')
  const [query, setQuery] = useState('')

  // Quiet reload: after the first load, data swaps in place without skeletons.
  const load = useCallback(async () => {
    if (!orgId) return
    // One round trip: everything the dashboard shows, fetched in parallel.
    const [c, m, it, sub, moments, armStats, u] = await Promise.all([
      supabase.from('campaigns').select('*').eq('org_id', orgId).order('created_at', { ascending: false }),
      supabase.from('metrics').select('*').order('collected_at', { ascending: true }),
      supabase.from('iterations').select('campaign_id,round_number,preflight_attempt,image_style,copy_tone'),
      supabase.from('subscriptions').select('status').maybeSingle(),
      // Market moments from the last week that nobody has dismissed.
      supabase
        .from('market_alerts')
        .select('id,campaign_id,kind,detail,created_at,campaigns(idea)')
        .eq('org_id', orgId)
        .is('dismissed_at', null)
        .gte('created_at', new Date(Date.now() - 7 * 86400000).toISOString())
        .order('created_at', { ascending: false })
        .limit(5),
      // The shared learning loop's size (every campaign on MarketingOS feeds it).
      supabase.from('bandit_arms').select('pulls'),
      supabase.rpc('org_usage', { p_org: orgId }),
    ])
    // Campaigns are the page; the rest degrade to empty. Say so rather than show a blank dashboard.
    toastLoadError(t, c.error, () => load())
    // RLS returns every organisation the user belongs to; show the active one.
    const inOrg = new Set(((c.data as Campaign[]) ?? []).map((x) => x.id))
    setCampaigns((c.data as Campaign[]) ?? [])
    setMetrics(((m.data as Metric[]) ?? []).filter((x) => inOrg.has(x.campaign_id)))
    setArms(((it.data as IterationArm[]) ?? []).filter((x) => inOrg.has(x.campaign_id)))
    setTier(sub.data?.status === 'subscribed' ? 'subscribed' : 'free')
    setAlerts((moments.data as unknown as MarketAlert[] | null) ?? [])
    const pulls = ((armStats.data as { pulls: number }[] | null) ?? []).map((a) => a.pulls ?? 0)
    setLoop(pulls.length ? { rounds: pulls.reduce((a, b) => a + b, 0), tried: pulls.filter((p) => p > 0).length } : null)
    setUsage((u.data as OrgUsage | null) ?? null)
    setFirstLoad(false)
  }, [orgId, t])

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
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'market_alerts' }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [load])

  // Dismissing hides an alert for everyone on the campaign (it's the same signal for all).
  async function dismissAlert(alertId: number) {
    setAlerts((list) => list.filter((a) => a.id !== alertId))
    const { error } = await supabase.from('market_alerts').update({ dismissed_at: new Date().toISOString() }).eq('id', alertId)
    toastFailure(t, error)
  }

  async function refresh() {
    setRefreshing(true)
    await load()
    setRefreshing(false)
  }

  async function createCampaign() {
    if (!idea.trim() || !productPhoto || !isWebLink(ctaLink) || creating || !canCreate) return
    setCreating(true)
    // The photo goes up first, into the user's own folder; the campaign gets its path.
    const userId = session?.user.id
    const ext = productPhoto.type === 'image/png' ? 'png' : productPhoto.type === 'image/webp' ? 'webp' : 'jpg'
    const path = `${userId}/${crypto.randomUUID()}.${ext}`
    const upload = await supabase.storage.from('product-photos').upload(path, productPhoto, { contentType: productPhoto.type })
    if (upload.error || !userId) {
      setCreating(false)
      toast.error(t('product.uploadFailed', { message: upload.error?.message ?? 'no session' }))
      return
    }
    const { error, response } = await supabase.functions.invoke('create-campaign', {
      body: {
        idea: idea.trim(), target_language: targetLanguage, org_id: orgId, ab_test: abTest,
        product_image_path: path, tagline: tagline.trim(), cta_url: ctaLink.trim(),
      },
    })
    setCreating(false)
    if (error) {
      // Plan limits come back as 429 with the reason in the body.
      let message = error.message
      if (response?.status === 429) {
        message = ((await response.json().catch(() => null)) as { error?: string } | null)?.error ?? message
      }
      toast.error(t('dash.dispatchFailed', { message }))
      return
    }
    toast.success(t('dash.dispatched'))
    setIdea('')
    setProductPhoto(null)
    setTagline('')
    setCtaLink('')
  }

  function onComposerKey(e: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault()
      createCampaign()
    }
  }

  // The sidebar's "New campaign" lands here with #new: go straight to the composer.
  useEffect(() => {
    if (hash !== '#new' || firstLoad) return
    composerRef.current?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    composerRef.current?.focus({ preventScroll: true })
  }, [hash, firstLoad])

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
  const avgReward = roundRewards.length ? roundRewards.reduce((s, r) => s + r.reward, 0) / roundRewards.length : 0
  const latestReward = roundRewards.length ? roundRewards[roundRewards.length - 1].reward : null
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
      mastodon: { likes: sum('mastodon', 'likes'), reposts: sum('mastodon', 'reposts'), replies: sum('mastodon', 'replies') },
      email: { clicks: sum('email', 'clicks'), recipients: sum('email', 'recipients') },
      hasBluesky: metrics.some((m) => m.channel === 'bluesky'),
      hasMastodon: metrics.some((m) => m.channel === 'mastodon'),
      hasEmail: metrics.some((m) => m.channel === 'email'),
    }
  }, [metrics])

  // The final pre-flight attempt of each measured round: the creative that ran.
  const finalAttempt = useMemo(() => {
    const map = new Map<string, IterationArm>()
    for (const it of arms) {
      const key = `${it.campaign_id}:${it.round_number}`
      const prev = map.get(key)
      if (!prev || it.preflight_attempt > prev.preflight_attempt) map.set(key, it)
    }
    return map
  }, [arms])

  // Arm leaderboard.
  const armRows = useMemo(() => {
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
      .slice(0, 3)
  }, [finalAttempt, roundRewards])

  // What the results say, in sentences: a copy tone or visual style that does
  // clearly better (or worse) than average within one industry, with 2+ rounds.
  const insights = useMemo(() => {
    const all = roundRewards.map((r) => r.reward)
    const overall = all.length ? all.reduce((a, b) => a + b, 0) / all.length : 0
    const groups = new Map<string, { kind: 'tone' | 'style'; value: string; domain: string; rewards: number[] }>()
    for (const r of roundRewards) {
      const it = finalAttempt.get(r.key)
      const domain = byId.get(r.campaign_id)?.domain_category
      if (!it || !domain) continue
      for (const [kind, value] of [['tone', it.copy_tone], ['style', it.image_style]] as const) {
        if (!value) continue
        const key = `${kind}|${value}|${domain}`
        const g = groups.get(key) ?? { kind, value, domain, rewards: [] }
        g.rewards.push(r.reward)
        groups.set(key, g)
      }
    }
    const scored = [...groups.values()]
      .filter((g) => g.rewards.length >= 2)
      .map((g) => ({ ...g, mean: g.rewards.reduce((a, b) => a + b, 0) / g.rewards.length }))
    const best = scored.filter((g) => overall > 0 && g.mean >= overall * 1.2).sort((a, b) => b.mean - a.mean).slice(0, 2)
    const worst = scored.filter((g) => g.mean <= overall * 0.8).sort((a, b) => a.mean - b.mean).slice(0, 1)
    return [...best.map((g) => ({ ...g, up: true })), ...worst.map((g) => ({ ...g, up: false }))].map((g) => ({
      key: `${g.kind}|${g.value}|${g.domain}`,
      up: g.up,
      text: t(g.up ? 'learn.best' : 'learn.worst', {
        what: t(g.kind === 'tone' ? 'learn.tone' : 'learn.style', { name: humanize(g.value) }),
        domain: humanize(g.domain),
        mean: g.mean.toFixed(2),
        n: g.rewards.length,
        lift: overall > 0 ? (g.mean / overall).toFixed(1) : '—',
      }),
    }))
  }, [roundRewards, finalAttempt, byId, t])

  const pipelineRows = STATUS_ORDER.map((s) => ({
    key: s,
    label: t(`dash.st_${s}`),
    value: campaigns.filter((c) => c.status === s).length,
  }))

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
    return events.sort((a, b) => b.at.localeCompare(a.at)).slice(0, 8)
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

  function jumpToHelp() {
    document.getElementById('help')?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }

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
          <button type="button" className={styles.helpBtn} onClick={jumpToHelp}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
              <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6v.6M12 17h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
            <span className={styles.helpLabel}>{t('dash.helpBtn')}</span>
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

      <MarketMoments alerts={alerts} onDismiss={dismissAlert} showCampaign />

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

      {/* ===== Start a campaign: composer + plan & usage, equal height ===== */}
      <h2 className={styles.sectionTitle}>{t('dash.secStart')}</h2>
      <section className={`${styles.panel} ${styles.composer} ${styles.hero} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
          <div className={styles.heroHead}>
            <span className={styles.heroIcon} aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none">
                <path d="M12 3l2.2 5.3L20 9l-4.4 3.8L17 18.5 12 15.6 7 18.5l1.4-5.7L4 9l5.8-.7z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
              </svg>
            </span>
            <div>
              <h2>{t('dashboard.createTitle')}</h2>
              <p className={styles.panelSub}>{t('dash.composerHint')}</p>
            </div>
            <kbd className={styles.kbd}>Ctrl ↵</kbd>
          </div>
          <div className={styles.textareaWrap}>
            <textarea
              ref={composerRef}
              value={idea}
              onChange={(e) => setIdea(e.target.value)}
              onKeyDown={onComposerKey}
              placeholder={t('dashboard.ideaPlaceholder')}
              rows={4}
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
          <ProductFields
            photo={productPhoto}
            onPhoto={setProductPhoto}
            tagline={tagline}
            onTagline={setTagline}
            link={ctaLink}
            onLink={setCtaLink}
          />
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
            <button type="button" className={styles.primaryBtn} onClick={createCampaign} disabled={creating || !idea.trim() || !productPhoto || !isWebLink(ctaLink) || !canCreate} title={!canCreate ? t('org.cantCreate') : !productPhoto ? t('product.photoNeeded') : undefined}>
              {creating && <span className={styles.spinner} aria-hidden="true" />}
              {creating ? t('dashboard.creating') : t('dashboard.createSubmit')}
              {!creating && (
                <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
          {/* Plan limits sit with the composer: they decide whether a campaign can start now. */}
          <div className={styles.heroPlan}>
            <div className={styles.heroPlanHead}>
              <span>{t('dash.planTitle')}</span>
              <span className={`${styles.tierBadge} ${tier === 'subscribed' ? styles.tierPaid : ''}`}>
                {tier === 'subscribed' ? t('dash.planSubscribed') : t('dash.planFree')}
              </span>
              <small>{t('dash.planRounds', { rounds: roundsCap })}</small>
            </div>
            {usage && <UsageMeters usage={usage} />}
            <div className={styles.heroPlanLinks}>
              <Link to="/settings#billing" className={`${styles.planLink} ${styles.upgradeLink} link-wipe`}>
                {tier === 'subscribed' ? t('dash.planManage') : t('billing.upgrade')} →
              </Link>
              <Link to="/settings#keys" className={`${styles.planLink} link-wipe`}>
                {t('dash.planKeys')} →
              </Link>
            </div>
          </div>
      </section>

      {/* ===== Performance: every number in one place ===== */}
      <h2 className={styles.sectionTitle}>{t('dash.secPerformance')}</h2>
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
            <Kpi index={3} label={t('dash.kpiActive')} value={activeShown} hint={t('dash.kpiActiveHint', { count: finished })} />
            <Kpi
              index={4}
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
            <Kpi index={5} label={t('dash.kpiEngagement')} value={engShown} hint={t('dash.kpiEngagementHint')} />
            <Kpi index={6} label={t('dash.kpiReward')} value={roundRewards.length ? rewardShown : '—'} hint={t('dash.kpiRewardHint')}>
              <Sparkline values={trend.slice(-12).map((p) => p.reward)} />
            </Kpi>
          </>
        )}
      </section>

      <section className={styles.row}>
        <div className={`${styles.panel} ${styles.trendPanel} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
          <div className={styles.panelHead}>
            <div>
              <h2>{t('dash.trendTitle')}</h2>
              <p className={styles.panelSub}>{t('dash.trendSub')}</p>
            </div>
          </div>
          <div className={styles.trendBody}>
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
          <dl className={styles.trendStats}>
            <div>
              <dt>{t('dash.trendRounds')}</dt>
              <dd>{roundRewards.length}</dd>
            </div>
            <div>
              <dt>{t('dash.trendAvg')}</dt>
              <dd>{roundRewards.length ? avgReward.toFixed(2) : '—'}</dd>
            </div>
            <div>
              <dt>{t('dash.trendLatest')}</dt>
              <dd>{latestReward !== null ? latestReward.toFixed(2) : '—'}</dd>
            </div>
          </dl>
        </div>

        <div className={styles.sideStack}>
          <div className={`${styles.panel} ${styles.enter}`} style={{ '--i': 8 } as CSSProperties}>
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
                  <span>{channelTotals.hasBluesky ? t('dash.blueskyDetail', channelTotals.bluesky) : t('dash.channelEmpty')}</span>
                </div>
                <b className={styles.channelTotal}>
                  {channelTotals.bluesky.likes + channelTotals.bluesky.reposts + channelTotals.bluesky.replies}
                </b>
              </div>
              {/* Only where it's switched on (a posting token is configured): no empty tile otherwise. */}
              {channelTotals.hasMastodon && (
                <div className={styles.channel}>
                  <span className={styles.channelIcon} aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M4 7.5A4.5 4.5 0 0 1 8.5 3h7A4.5 4.5 0 0 1 20 7.5V12a4.5 4.5 0 0 1-4.5 4.5H11a2.5 2.5 0 0 0 2.5 2.5H17v1.5c-1.2.3-2.4.5-3.5.5A6.5 6.5 0 0 1 7 14.5h-.5A2.5 2.5 0 0 1 4 12z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                      <path d="M8.5 12V8.6a1.6 1.6 0 0 1 3.2 0V10m0 0V8.6a1.6 1.6 0 0 1 3.2 0V12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    </svg>
                  </span>
                  <div>
                    <strong>Mastodon</strong>
                    <span>{t('dash.mastodonDetail', channelTotals.mastodon)}</span>
                  </div>
                  <b className={styles.channelTotal}>
                    {channelTotals.mastodon.likes + channelTotals.mastodon.reposts + channelTotals.mastodon.replies}
                  </b>
                </div>
              )}
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

          <div className={`${styles.panel} ${styles.grow} ${styles.enter}`} style={{ '--i': 9 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('learn.title')}</h2>
                <p className={styles.panelSub}>{t('learn.sub')}</p>
              </div>
            </div>
            {insights.length > 0 ? (
              <ul className={styles.insights}>
                {insights.map((i) => (
                  <li key={i.key} className={i.up ? styles.insightUp : styles.insightDown}>
                    <span aria-hidden="true">{i.up ? '↑' : '↓'}</span>
                    {i.text}
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.muted}>{t('learn.empty')}</p>
            )}
            {armRows.length > 0 && (
              <>
                <h3 className={styles.miniHead}>{t('learn.topArms')}</h3>
                <BarList rows={armRows} max={1} format={(v) => v.toFixed(2)} />
              </>
            )}
            <p className={styles.panelNote}>
              {loop ? t('learn.loop', { rounds: loop.rounds, tried: loop.tried }) : t('dash.armsNote')}{' '}
              <Link to="/playbooks" className={`${styles.planLink} link-wipe`}>
                {t('pb.open')} →
              </Link>
            </p>
          </div>
        </div>
      </section>

      {/* ===== Campaigns: full-width table, pipeline strip on top filters it ===== */}
      <h2 className={styles.sectionTitle}>{t('dash.secCampaigns')}</h2>
      <section className={`${styles.panel} ${styles.tablePanel} ${styles.enter}`} style={{ '--i': 10 } as CSSProperties} id="campaigns">
        <div className={styles.tableHead}>
          <div>
            <h2>{t('dash.campaignsTitle')}</h2>
            <p className={styles.panelSub}>{t('dash.pipelineSub')}</p>
          </div>
          <div className={styles.search}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
              <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('dash.search')} aria-label={t('dash.search')} />
          </div>
        </div>

        {!firstLoad && campaigns.length > 0 && (
          <div className={styles.pipeline} aria-label={t('dash.pipelineTitle')}>
            <div className={styles.pipelineBar} aria-hidden="true">
              {pipelineRows
                .filter((r) => r.value > 0)
                .map((r) => (
                  <span key={r.key} className={styles[`seg_${r.key}`]} style={{ flexGrow: r.value }} title={`${r.label}: ${r.value}`} />
                ))}
            </div>
            <ul className={styles.pipelineLegend}>
              {pipelineRows.map((r) => (
                <li key={r.key}>
                  <button type="button" className={`${styles.legendItem} ${r.value === 0 ? styles.legendZero : ''}`} onClick={() => selectPipeline(r.key)} disabled={r.value === 0}>
                    <span className={`${styles.legendDot} ${styles[`seg_${r.key}`]}`} aria-hidden="true" />
                    {r.label}
                    <b>{r.value}</b>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}

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
      </section>

      {/* ===== Help & activity ===== */}
      <h2 className={styles.sectionTitle}>{t('dash.secHelp')}</h2>
      <section className={styles.rowHalves}>
        <div className={`${styles.panel} ${styles.help} ${styles.enter}`} style={{ '--i': 11 } as CSSProperties} id="help">
          <div className={styles.panelHead}>
            <div>
              <h2>{t('dash.helpTitle')}</h2>
              <p className={styles.panelSub}>{t('dash.helpSub')}</p>
            </div>
          </div>
          <div className={styles.helpBody}>
            {/* Placeholder until a real walkthrough video exists. */}
            <div className={styles.video}>
              <span className={styles.play} aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8 5.5v13l11-6.5z" />
                </svg>
              </span>
              <span className={styles.videoLabel}>{t('dash.videoPlaceholder')}</span>
            </div>
            <div className={styles.helpIntro}>
              <h3>{t('dash.guideTitle')}</h3>
              <p>{t('dash.guideBody')}</p>
            </div>
          </div>
          <ul className={styles.helpLinks}>
            {(
              [
                ['/docs', 'helpDocs', 'M5 4h10l4 4v12H5zM14 4v5h5M8 13h8M8 17h6'],
                ['/status', 'helpStatus', 'M3 12h4l3-7 4 14 3-7h4'],
                ['/contact', 'helpContact', 'M4 6h16v10H8l-4 4zM8 10h8'],
                ['/models', 'helpModel', 'M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5'],
              ] as const
            ).map(([to, key, d]) => (
              <li key={to}>
                <Link to={to} className={`${styles.helpLink} wipe-host`}>
                  <span className={styles.helpIcon} aria-hidden="true">
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d={d} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </span>
                  <span className={styles.helpText}>
                    <span className="link-wipe">{t(`dash.${key}`)}</span>
                    <small>{t(`dash.${key}Sub`)}</small>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <p className={styles.helpTip}>
            <kbd className={styles.kbd}>Ctrl ↵</kbd> {t('dash.helpShortcut')}
          </p>
        </div>

        <div className={`${styles.panel} ${styles.activityPanel} ${styles.enter}`} style={{ '--i': 12 } as CSSProperties}>
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
          <Link to="/calendar" className={`${styles.planLink} link-wipe`}>
            {t('dash.activityCalendar')} →
          </Link>
        </div>
      </section>
    </div>
  )
}
