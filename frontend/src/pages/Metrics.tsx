import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/shell.module.css'
import type { Campaign, Iteration, Metric } from '../lib/types'

const CHART_WIDTH = 600
const CHART_HEIGHT = 160
const CHART_PADDING = 24

function RewardTrendChart({ points }: { points: { round: number; reward: number }[] }) {
  const { t } = useTranslation()
  if (points.length === 0) return <p className={`text-sm ${styles.muted}`}>{t('metrics.noMetrics')}</p>

  const innerWidth = CHART_WIDTH - CHART_PADDING * 2
  const innerHeight = CHART_HEIGHT - CHART_PADDING * 2
  const stepX = points.length > 1 ? innerWidth / (points.length - 1) : 0

  const coords = points.map((p, i) => ({
    x: CHART_PADDING + i * stepX,
    y: CHART_PADDING + innerHeight * (1 - p.reward),
    ...p,
  }))
  const path = coords.map((c, i) => `${i === 0 ? 'M' : 'L'} ${c.x} ${c.y}`).join(' ')

  return (
    <svg viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="w-full h-40">
      <line
        x1={CHART_PADDING}
        y1={CHART_HEIGHT - CHART_PADDING}
        x2={CHART_WIDTH - CHART_PADDING}
        y2={CHART_HEIGHT - CHART_PADDING}
        stroke="var(--mos-surface-border)"
      />
      <line
        x1={CHART_PADDING}
        y1={CHART_PADDING}
        x2={CHART_PADDING}
        y2={CHART_HEIGHT - CHART_PADDING}
        stroke="var(--mos-surface-border)"
      />
      <path d={path} fill="none" stroke="var(--mos-accent)" strokeWidth={2} />
      {coords.map((c) => (
        <g key={c.round}>
          <circle cx={c.x} cy={c.y} r={3} fill="var(--mos-accent)" />
          <text x={c.x} y={CHART_HEIGHT - 6} textAnchor="middle" fill="var(--mos-text-muted)" fontSize={10}>
            R{c.round}
          </text>
        </g>
      ))}
    </svg>
  )
}

export default function Metrics() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])

  useEffect(() => {
    async function load() {
      if (!id) return
      const [{ data: campaignData }, { data: iterationData }, { data: metricData }] = await Promise.all([
        supabase.from('campaigns').select('*').eq('id', id).single(),
        supabase.from('iterations').select('*').eq('campaign_id', id).order('round_number'),
        supabase.from('metrics').select('*').eq('campaign_id', id).order('round_number'),
      ])
      setCampaign(campaignData as Campaign)
      setIterations((iterationData as Iteration[]) ?? [])
      setMetrics((metricData as Metric[]) ?? [])
    }
    load()
  }, [id])

  if (!campaign) return <p className={`p-8 ${styles.muted}`}>{t('common.loading')}</p>

  const rounds = iterations.map((it) => it.round_number)
  const trend = rounds.map((round) => {
    const roundMetrics = metrics.filter((m) => m.round_number === round)
    const reward = roundMetrics.length ? roundMetrics.reduce((sum, m) => sum + m.reward, 0) / roundMetrics.length : 0
    return { round, reward }
  })

  return (
    <div className={`max-w-3xl mx-auto p-8 space-y-8 ${styles.shell}`}>
      <Link to={`/campaigns/${id}`} className={`text-sm ${styles.muted} hover:underline`}>
        {t('metrics.backLink')}
      </Link>

      <div>
        <h1 className="text-2xl">{t('metrics.title', { idea: campaign.idea })}</h1>
        <p className={`text-sm ${styles.muted} mt-1`}>{t('metrics.subtitle')}</p>
      </div>

      <section>
        <h2 className="text-lg font-medium mb-2">{t('metrics.rewardTrendTitle')}</h2>
        <RewardTrendChart points={trend} />
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">{t('metrics.perRoundTitle')}</h2>
        {iterations.map((it) => {
          const roundMetrics = metrics.filter((m) => m.round_number === it.round_number)
          return (
            <div key={it.id} className={`${styles.card} p-4`}>
              <div className="flex justify-between items-center mb-2">
                <span className="font-medium">{t('metrics.round', { round: it.round_number })}</span>
                <span className={`text-xs ${styles.muted} ${styles.mono}`}>
                  {t('metrics.arm', { style: it.image_style ?? '—', tone: it.copy_tone ?? '—', index: it.arm_index ?? '—' })}
                </span>
              </div>
              {roundMetrics.length === 0 ? (
                <p className={`text-sm ${styles.muted}`}>{t('metrics.noRoundMetrics')}</p>
              ) : (
                <table className={`${styles.table} text-sm`}>
                  <thead>
                    <tr>
                      <th className="pr-4 pb-1">{t('metrics.channel')}</th>
                      <th className="pr-4 pb-1">{t('metrics.rawMetrics')}</th>
                      <th className="pb-1">{t('metrics.reward')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roundMetrics.map((m) => (
                      <tr key={m.id}>
                        <td className="pr-4 py-1 capitalize">{m.channel}</td>
                        <td className={`pr-4 py-1 text-xs ${styles.mono}`}>
                          {Object.entries(m.raw_metrics)
                            .map(([k, v]) => `${k}=${v}`)
                            .join(', ')}
                        </td>
                        <td className="py-1">{m.reward.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )
        })}
      </section>
    </div>
  )
}
