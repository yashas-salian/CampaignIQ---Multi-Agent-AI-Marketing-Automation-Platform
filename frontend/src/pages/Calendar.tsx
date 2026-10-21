import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { Campaign, Metric } from '../lib/types'
import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './Calendar.module.css'

// Matches METRICS_WAIT_HOURS in src/constants.py (the default the workers use).
const METRICS_WAIT_HOURS = 6

type EventKind = 'created' | 'sent' | 'metrics'
interface CalEvent {
  day: string // YYYY-MM-DD, local time
  kind: EventKind
  campaign: Campaign
  label: string
}

interface Delivery {
  campaign_id: string
  round_number: number
  channel: string
  status: string
  updated_at: string
}

interface Gate {
  campaign_id: string
  gate_number: number
  round_number: number
  created_at: string
}

const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const ACTIVE = ['created', 'awaiting_gate_1', 'awaiting_gate_2', 'awaiting_metrics', 'awaiting_next_round']

/** Month view of what happened and what's due, plus the organisation's whole portfolio. */
export default function Calendar() {
  const { t, i18n } = useTranslation()
  const { active } = useOrg()
  const [month, setMonth] = useState(() => {
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), 1)
  })
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [gates, setGates] = useState<Gate[]>([])
  const [metrics, setMetrics] = useState<Metric[]>([])

  const load = useCallback(async () => {
    if (!active) return
    const { data: c } = await supabase.from('campaigns').select('*').eq('org_id', active.id).order('created_at', { ascending: false })
    const list = (c as Campaign[] | null) ?? []
    setCampaigns(list)
    const ids = list.map((x) => x.id)
    if (!ids.length) return
    const [{ data: d }, { data: g }, { data: m }] = await Promise.all([
      supabase.from('deliveries').select('campaign_id,round_number,channel,status,updated_at').in('campaign_id', ids).in('status', ['sent', 'dry_run']),
      supabase.from('gate_decisions').select('campaign_id,gate_number,round_number,created_at').in('campaign_id', ids).is('decided_at', null),
      supabase.from('metrics').select('*').in('campaign_id', ids),
    ])
    setDeliveries((d as Delivery[] | null) ?? [])
    setGates((g as Gate[] | null) ?? [])
    setMetrics((m as Metric[] | null) ?? [])
  }, [active])

  useEffect(() => {
    load()
  }, [load])

  const events = useMemo(() => {
    const out: CalEvent[] = []
    const byId = new Map(campaigns.map((c) => [c.id, c]))
    for (const c of campaigns) {
      out.push({ day: dayKey(new Date(c.created_at)), kind: 'created', campaign: c, label: t('cal.created') })
      if (c.status === 'awaiting_metrics' && c.distributed_at) {
        const due = new Date(new Date(c.distributed_at).getTime() + METRICS_WAIT_HOURS * 3600_000)
        out.push({ day: dayKey(due), kind: 'metrics', campaign: c, label: t('cal.metricsDue', { round: c.current_round }) })
      }
    }
    const seen = new Set<string>()
    for (const d of deliveries) {
      const c = byId.get(d.campaign_id)
      const key = `${d.campaign_id}-${d.round_number}`
      if (!c || seen.has(key)) continue
      seen.add(key)
      out.push({ day: dayKey(new Date(d.updated_at)), kind: 'sent', campaign: c, label: t('cal.sent', { round: d.round_number }) })
    }
    return out
  }, [campaigns, deliveries, t])

  const grid = useMemo(() => {
    const first = new Date(month)
    const start = new Date(first)
    start.setDate(1 - ((first.getDay() + 6) % 7)) // weeks start on Monday
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start)
      d.setDate(start.getDate() + i)
      return d
    })
  }, [month])

  const byDay = useMemo(() => {
    const map = new Map<string, CalEvent[]>()
    for (const e of events) map.set(e.day, [...(map.get(e.day) ?? []), e])
    return map
  }, [events])

  const bestReward = (id: string) => {
    const rewards = metrics.filter((m) => m.campaign_id === id).map((m) => m.reward)
    return rewards.length ? Math.max(...rewards) : null
  }

  const monthLabel = new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' }).format(month)
  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Intl.DateTimeFormat(i18n.language, { weekday: 'short' }).format(new Date(2024, 0, 1 + i)),
  )
  const today = dayKey(new Date())
  const shortDate = new Intl.DateTimeFormat(i18n.language, { day: 'numeric', month: 'short' })

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('cal.eyebrow')}</span>
          <h1 className={styles.title}>{t('cal.title')}</h1>
          <p className={styles.subtitle}>{t('cal.subtitle')}</p>
        </div>
      </header>

      {gates.length > 0 && (
        <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('cal.waiting', { count: gates.length })}</h2>
          </div>
          <ul className={local.waiting}>
            {gates.map((g) => {
              const c = campaigns.find((x) => x.id === g.campaign_id)
              if (!c) return null
              const hours = Math.floor((Date.now() - new Date(g.created_at).getTime()) / 3600_000)
              return (
                <li key={`${g.campaign_id}-${g.gate_number}-${g.round_number}`}>
                  <Link to={`/campaigns/${c.id}`} className="link-wipe">{c.idea}</Link>
                  <span className={styles.chip}>{t('cal.gate', { gate: g.gate_number, round: g.round_number })}</span>
                  <span className={styles.muted}>{t('cal.waitingFor', { hours })}</span>
                </li>
              )
            })}
          </ul>
        </section>
      )}

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
        <div className={local.monthHead}>
          <h2>{monthLabel}</h2>
          <div className={local.monthNav}>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} aria-label={t('cal.prev')} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => setMonth(new Date(new Date().getFullYear(), new Date().getMonth(), 1))}>{t('cal.today')}</button>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} aria-label={t('cal.next')} onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button>
          </div>
        </div>
        <div className={local.legend}>
          {(['created', 'sent', 'metrics'] as EventKind[]).map((k) => (
            <span key={k}><i className={local[k]} />{t(`cal.legend_${k}`)}</span>
          ))}
        </div>
        <div className={local.grid} role="grid" aria-label={monthLabel}>
          {weekdays.map((w) => <div key={w} className={local.weekday} role="columnheader">{w}</div>)}
          {grid.map((d) => {
            const key = dayKey(d)
            const dayEvents = byDay.get(key) ?? []
            return (
              <div
                key={key}
                role="gridcell"
                className={`${local.cell} ${d.getMonth() !== month.getMonth() ? local.outside : ''} ${key === today ? local.today : ''}`}
              >
                <span className={local.date}>{d.getDate()}</span>
                {dayEvents.slice(0, 3).map((e, i) => (
                  <Link key={i} to={`/campaigns/${e.campaign.id}`} className={`${local.event} ${local[e.kind]}`} title={`${e.label}: ${e.campaign.idea}`}>
                    {e.label} · {e.campaign.idea}
                  </Link>
                ))}
                {dayEvents.length > 3 && <span className={local.more}>{t('cal.more', { count: dayEvents.length - 3 })}</span>}
              </div>
            )
          })}
        </div>
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('cal.portfolio')}</h2>
          <span className={styles.chip}>{t('cal.activeCount', { count: campaigns.filter((c) => ACTIVE.includes(c.status)).length })}</span>
        </div>
        {campaigns.length === 0 ? (
          <p className={styles.muted}>{t('cal.empty')}</p>
        ) : (
          <div className={local.tableWrap}>
            <table className={local.table}>
              <thead>
                <tr>
                  <th>{t('cal.campaign')}</th>
                  <th>{t('cal.status')}</th>
                  <th>{t('cal.rounds')}</th>
                  <th>{t('cal.best')}</th>
                  <th>{t('cal.started')}</th>
                  <th>{t('cal.lastActivity')}</th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => {
                  const best = bestReward(c.id)
                  return (
                    <tr key={c.id}>
                      <td><Link to={`/campaigns/${c.id}`} className="link-wipe">{c.idea}</Link></td>
                      <td><span className={styles.chip}>{c.status.replace(/_/g, ' ')}</span></td>
                      <td>{c.current_round}{c.max_rounds ? ` / ${c.max_rounds}` : ''}</td>
                      <td>{best === null ? '—' : best.toFixed(2)}</td>
                      <td>{shortDate.format(new Date(c.created_at))}</td>
                      <td>{shortDate.format(new Date(c.updated_at))}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}
