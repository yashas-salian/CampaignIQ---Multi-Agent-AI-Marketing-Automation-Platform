import type { CSSProperties } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import RewardChart, { type RewardPoint } from '../components/RewardChart'
import { supabase } from '../lib/supabaseClient'
import type { AbTestResult, Campaign, Iteration, Metric } from '../lib/types'
import styles from '../styles/app.module.css'
import local from './Metrics.module.css'

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const KNOWN_KEYS = ['likes', 'reposts', 'replies', 'clicks', 'recipients']

/** Engagement = every counted interaction; "recipients" is a denominator, not engagement. */
const engagementOf = (m: Metric) =>
  Object.entries(m.raw_metrics).reduce((sum, [k, v]) => (k === 'recipients' ? sum : sum + (Number(v) || 0)), 0)

function ChannelIcon({ channel }: { channel: Metric['channel'] }) {
  if (channel === 'email') {
    return (
      <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.8" />
        <path d="M3.5 6.5L12 13l8.5-6.5" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 12a8 8 0 1 1 3.3 6.5L4 20l1.4-3.4A8 8 0 0 1 4 12z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
    </svg>
  )
}

function AbResult({ result }: { result: AbTestResult }) {
  const { t } = useTranslation()
  const pct = (r: number) => `${(r * 100).toFixed(1)}%`
  const verdict = result.winner
    ? t('ab.winner', { variant: result.winner.toUpperCase(), p: result.p_value })
    : t('ab.noWinner', { p: result.p_value ?? '—' })
  return (
    <span className={styles.chip} title={t('ab.explain')}>
      A {pct(result.rate_a)} · B {pct(result.rate_b)} · {verdict}
    </span>
  )
}

export default function Metrics() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    const [{ data: campaignData }, { data: iterationData }, { data: metricData }] = await Promise.all([
      supabase.from('campaigns').select('*').eq('id', id).maybeSingle(),
      supabase.from('iterations').select('*').eq('campaign_id', id).order('round_number').order('preflight_attempt'),
      supabase.from('metrics').select('*').eq('campaign_id', id).order('round_number'),
    ])
    setCampaign((campaignData as Campaign) ?? null)
    setIterations((iterationData as Iteration[]) ?? [])
    setMetrics((metricData as Metric[]) ?? [])
    setLoaded(true)
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // New metrics land when the hourly worker collects them; refresh quietly.
  useEffect(() => {
    if (!id) return
    const channel = supabase
      .channel(`metrics-${id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'metrics', filter: `campaign_id=eq.${id}` }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [id, load])

  // Final attempt per round = the creative that actually went out.
  const rounds = useMemo(() => {
    const byRound = new Map<number, Iteration>()
    for (const it of iterations) byRound.set(it.round_number, it)
    return [...byRound.values()].sort((a, b) => a.round_number - b.round_number)
  }, [iterations])

  const rewardByRound = useMemo(() => {
    const out = new Map<number, number>()
    for (const r of rounds) {
      const ms = metrics.filter((m) => m.round_number === r.round_number)
      if (ms.length) out.set(r.round_number, ms.reduce((s, m) => s + m.reward, 0) / ms.length)
    }
    return out
  }, [rounds, metrics])

  const trend: RewardPoint[] = rounds
    .filter((r) => rewardByRound.has(r.round_number))
    .map((r) => {
      const reward = rewardByRound.get(r.round_number) ?? 0
      return {
        key: String(r.round_number),
        reward,
        label: `R${r.round_number}`,
        title: t('dash.trendTooltip', { round: r.round_number, reward: reward.toFixed(2) }),
        detail: r.image_style && r.copy_tone ? `${humanize(r.image_style)} × ${r.copy_tone.replace(/_/g, ' ')}` : undefined,
      }
    })

  const rewards = [...rewardByRound.values()]
  const avg = rewards.length ? rewards.reduce((a, b) => a + b, 0) / rewards.length : null
  const best = rewards.length ? Math.max(...rewards) : null
  const engagement = metrics.reduce((s, m) => s + engagementOf(m), 0)
  const metricLabel = (k: string) => (KNOWN_KEYS.includes(k) ? t(`mx.k_${k}`) : humanize(k))

  if (!loaded) {
    return (
      <div className={styles.page}>
        <span className={styles.skeleton} style={{ height: 16, width: 160 }} />
        <span className={styles.skeleton} style={{ height: 40, width: '55%' }} />
        <div className={styles.stats}>
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className={styles.skeleton} style={{ height: 112 }} />
          ))}
        </div>
        <span className={styles.skeleton} style={{ height: 280 }} />
      </div>
    )
  }

  if (!campaign) {
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

  const stats = [
    { label: t('mx.statRounds'), value: String(rewards.length), hint: campaign.max_rounds ? `/ ${campaign.max_rounds}` : '' },
    { label: t('mx.statAvg'), value: avg === null ? '—' : avg.toFixed(2), hint: t('dash.kpiRewardHint') },
    { label: t('mx.statBest'), value: best === null ? '—' : best.toFixed(2), hint: t('dash.kpiRewardHint') },
    { label: t('mx.statEngagement'), value: String(engagement), hint: t('dash.kpiEngagementHint') },
  ]

  return (
    <div className={styles.page}>
      <div className={`${styles.crumbs} ${styles.enter}`}>
        <Link to={`/campaigns/${id}`} className={`${styles.back} link-wipe`}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('mx.back')}
        </Link>
      </div>

      <header className={`${styles.header} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
        <div>
          <span className={styles.eyebrow}>{t('metrics.rewardTrendTitle')}</span>
          <h1 className={styles.title}>{campaign.idea}</h1>
          <p className={styles.subtitle}>{t('metrics.subtitle')}</p>
        </div>
      </header>

      <section className={styles.stats}>
        {stats.map((s, i) => (
          <div key={s.label} className={`${styles.panel} ${styles.stat} ${styles.enter}`} style={{ '--i': i + 2 } as CSSProperties}>
            <span className={styles.statLabel}>{s.label}</span>
            <span className={styles.statValue}>{s.value}</span>
            <span className={styles.statHint}>{s.hint}</span>
          </div>
        ))}
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 6 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('metrics.rewardTrendTitle')}</h2>
        </div>
        {trend.length === 0 ? (
          <div className={local.emptyChart}>
            <svg viewBox="0 0 120 48" aria-hidden="true">
              <path d="M4 40 L30 30 L52 34 L78 18 L116 10" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 5" strokeLinecap="round" />
            </svg>
            <p>{t('metrics.noMetrics')}</p>
          </div>
        ) : (
          <RewardChart points={trend} ariaLabel={t('metrics.rewardTrendTitle')} showXLabels />
        )}
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('metrics.perRoundTitle')}</h2>
        </div>
        {rounds.length === 0 ? (
          <p className={styles.muted}>{t('metrics.noMetrics')}</p>
        ) : (
          <div className={local.rounds}>
            {rounds.map((it, i) => {
              const roundMetrics = metrics.filter((m) => m.round_number === it.round_number)
              const reward = rewardByRound.get(it.round_number)
              return (
                <article key={it.id} className={local.round} style={{ '--i': i } as CSSProperties}>
                  <header className={local.roundHead}>
                    <span className={local.roundNum}>R{it.round_number}</span>
                    <div className={local.roundTitle}>
                      <strong>{t('metrics.round', { round: it.round_number })}</strong>
                      {it.image_style && it.copy_tone && (
                        <span>
                          {humanize(it.image_style)} × {it.copy_tone.replace(/_/g, ' ')}
                          {it.arm_index !== null && ` · ${t('mx.armIndex', { index: it.arm_index })}`}
                        </span>
                      )}
                    </div>
                    <div className={local.roundReward}>
                      <span>{t('metrics.reward')}</span>
                      <b>{reward === undefined ? '—' : reward.toFixed(2)}</b>
                    </div>
                  </header>
                  {roundMetrics.length === 0 ? (
                    <p className={local.pending}>
                      <span className={local.pendingDot} aria-hidden="true" />
                      {t('mx.pending')}
                    </p>
                  ) : (
                    <ul className={local.channels}>
                      {roundMetrics.map((m) => (
                        <li key={m.id}>
                          <span className={local.channelIcon}>
                            <ChannelIcon channel={m.channel} />
                          </span>
                          <span className={local.channelName}>{humanize(m.channel)}</span>
                          <span className={local.raw}>
                            {Object.entries(m.raw_metrics)
                              .filter(([, v]) => typeof v === 'number')
                              .map(([k, v]) => (
                                <span key={k} className={styles.chip}>
                                  {v as number} {metricLabel(k)}
                                </span>
                              ))}
                            {typeof m.raw_metrics.ab_test === 'object' && <AbResult result={m.raw_metrics.ab_test as AbTestResult} />}
                          </span>
                          <span className={local.bar}>
                            <span className={styles.track}>
                              <span className={styles.fill} style={{ width: `${Math.min(1, m.reward) * 100}%` }} />
                            </span>
                            <b>{m.reward.toFixed(2)}</b>
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
