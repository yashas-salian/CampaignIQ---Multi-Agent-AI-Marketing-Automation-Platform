import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import type { Campaign, Iteration, Metric } from '../lib/types'

const CHART_WIDTH = 600
const CHART_HEIGHT = 160
const CHART_PADDING = 24

function RewardTrendChart({ points }: { points: { round: number; reward: number }[] }) {
  const { t } = useTranslation()
  if (points.length === 0) return <p className="text-sm text-gray-500">{t('metrics.noMetrics')}</p>

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
        stroke="currentColor"
        className="text-gray-300"
      />
      <line x1={CHART_PADDING} y1={CHART_PADDING} x2={CHART_PADDING} y2={CHART_HEIGHT - CHART_PADDING} stroke="currentColor" className="text-gray-300" />
      <path d={path} fill="none" stroke="currentColor" className="text-purple-600" strokeWidth={2} />
      {coords.map((c) => (
        <g key={c.round}>
          <circle cx={c.x} cy={c.y} r={3} className="fill-purple-600" />
          <text x={c.x} y={CHART_HEIGHT - 6} textAnchor="middle" className="fill-gray-500 text-[10px]">
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

  if (!campaign) return <p className="p-8 text-gray-500">{t('common.loading')}</p>

  const rounds = iterations.map((it) => it.round_number)
  const trend = rounds.map((round) => {
    const roundMetrics = metrics.filter((m) => m.round_number === round)
    const reward = roundMetrics.length ? roundMetrics.reduce((sum, m) => sum + m.reward, 0) / roundMetrics.length : 0
    return { round, reward }
  })

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-8">
      <Link to={`/campaigns/${id}`} className="text-sm text-gray-500 hover:underline">
        {t('metrics.backLink')}
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">{t('metrics.title', { idea: campaign.idea })}</h1>
        <p className="text-sm text-gray-500 mt-1">{t('metrics.subtitle')}</p>
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
            <div key={it.id} className="border rounded-lg p-4">
              <div className="flex justify-between items-center mb-2">
                <span className="font-medium">{t('metrics.round', { round: it.round_number })}</span>
                <span className="text-xs text-gray-500 font-mono">
                  {t('metrics.arm', { style: it.image_style ?? '—', tone: it.copy_tone ?? '—', index: it.arm_index ?? '—' })}
                </span>
              </div>
              {roundMetrics.length === 0 ? (
                <p className="text-sm text-gray-500">{t('metrics.noRoundMetrics')}</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-gray-500">
                      <th className="pr-4 font-normal">{t('metrics.channel')}</th>
                      <th className="pr-4 font-normal">{t('metrics.rawMetrics')}</th>
                      <th className="font-normal">{t('metrics.reward')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roundMetrics.map((m) => (
                      <tr key={m.id} className="border-t">
                        <td className="pr-4 py-1 capitalize">{m.channel}</td>
                        <td className="pr-4 py-1 font-mono text-xs">
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
