import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { CreativeIntervention, FatigueAlert, FatigueReport, FatigueSegment, FatigueStatus, FatigueStrategy } from '../lib/types'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'
import Select from './Select'
import app from '../styles/app.module.css'
import styles from './CreativeFatigue.module.css'

const STRATEGIES: FatigueStrategy[] = ['NEW_HOOK', 'NEW_VISUAL', 'NEW_ANGLE', 'NEW_OFFER_FRAMING']
const pct = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(d)}%`)
const signed = (x: number, d = 1) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x * 100).toFixed(d)}`

/** Wilson 95% interval, as the worker computes it. */
function wilson(k: number, n: number): [number, number] {
  if (!n) return [0, 0]
  const z = 1.959963984540054
  const p = k / n
  const denom = 1 + (z * z) / n
  const centre = (p + (z * z) / (2 * n)) / denom
  const half = (z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n))) / denom
  return [Math.max(0, centre - half), Math.min(1, centre + half)]
}

const TONE: Record<FatigueStatus, string> = {
  NO_FATIGUE: styles.toneOk,
  FATIGUE_SUSPECTED: styles.toneWarn,
  FATIGUE_CONFIRMED: styles.toneBad,
  NOT_ATTRIBUTABLE: styles.toneNeutral,
  INSUFFICIENT_DATA: styles.toneNeutral,
  NOT_MEASURABLE: styles.toneNeutral,
}
const ICON: Record<FatigueStatus, string> = {
  NO_FATIGUE: 'M5 13l4 4L19 7',
  FATIGUE_SUSPECTED: 'M12 8v5M12 16.5v.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  FATIGUE_CONFIRMED: 'M3 7l6 6 4-4 8 8M21 11v6h-6',
  NOT_ATTRIBUTABLE: 'M5 12h14',
  INSUFFICIENT_DATA: 'M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01',
  NOT_MEASURABLE: 'M5 12h14',
}

/** Rate per round with its 95% interval; the fresh baseline as a band. */
function RoundsChart({ seg, label }: { seg: FatigueSegment; label: string }) {
  const { t } = useTranslation()
  const rows = seg.periods.filter((p) => p.exposures)
  const max = Math.max(0.01, ...rows.map((p) => wilson(p.successes ?? 0, p.exposures ?? 0)[1]), seg.baseline?.interval[1] ?? 0) * 1.1
  const x = (v: number) => `${(Math.min(v, max) / max) * 100}%`
  return (
    <figure className={styles.chart} aria-label={t('cf.chartCaption', { label })}>
      {rows.map((p) => {
        const k = p.successes ?? 0
        const n = p.exposures ?? 0
        const [lo, hi] = wilson(k, n)
        const recent = seg.recent?.rounds.includes(p.round)
        const tip = t('cf.tip', { round: p.round, rate: pct(k / n), k, n, lo: pct(lo), hi: pct(hi) })
        return (
          <div key={p.round} className={styles.row}>
            <span className={styles.rowLabel}>{t('cf.round', { n: p.round })}{p.stale ? ` · ${t('cf.stale')}` : ''}</span>
            <div className={styles.track}>
              {seg.baseline && <span className={styles.band} style={{ left: x(seg.baseline.interval[0]), width: `calc(${x(seg.baseline.interval[1])} - ${x(seg.baseline.interval[0])})` }} aria-hidden="true" />}
              <span className={styles.whisker} style={{ left: x(lo), width: `calc(${x(hi)} - ${x(lo)})` }} aria-hidden="true" />
              <button type="button" className={`${styles.dot} ${recent ? styles.dotRecent : ''}`} style={{ left: x(k / n) }} aria-label={tip} data-tip={tip} />
            </div>
          </div>
        )
      })}
      <div className={styles.row} aria-hidden="true">
        <span />
        <div className={styles.axis}><span style={{ left: '0%' }}>0%</span><span style={{ left: '100%' }}>{pct(max)}</span></div>
      </div>
      <figcaption className={styles.caption}>{t('cf.chartCaption', { label })}</figcaption>
    </figure>
  )
}

function SegmentCard({ seg, alert, pending, canEdit, onDone }: {
  seg: FatigueSegment
  alert: FatigueAlert | undefined
  pending: CreativeIntervention | undefined
  canEdit: boolean
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [strategy, setStrategy] = useState<FatigueStrategy>(pending?.strategy ?? seg.suggested_strategy ?? 'NEW_HOOK')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const label = seg.channel === 'email' ? t('cf.emailVariant', { v: seg.segment.toUpperCase() }) : t(`cf.channel.${seg.channel}`, seg.channel)

  async function refresh() {
    if (!alert) return
    setBusy(true)
    const { error } = await supabase.rpc('request_creative_refresh', { p_alert: alert.id, p_strategy: strategy })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('cf.refreshToast'))
    onDone()
  }

  async function keep() {
    if (!alert) return
    setBusy(true)
    const { error } = await supabase.rpc('dismiss_fatigue_alert', { p_alert: alert.id, p_note: note.trim() || null })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('cf.keptToast'))
    onDone()
  }

  const sim = seg.similarity
  const record = seg.strategy_record
  return (
    <article className={styles.segment} data-testid={`fatigue-${seg.channel}-${seg.segment}`}>
      <div className={`${styles.verdict} ${TONE[seg.status]}`}>
        <span className={styles.icon}><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d={ICON[seg.status]} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg></span>
        <div>
          <strong>{label}: {t(`cf.status.${seg.status}`)}</strong>
          <p>{t(`cf.reason.${seg.reason}`, { min: seg.min_exposures, periods: seg.min_periods })}</p>
        </div>
        <span className={styles.rec}>{t(`cf.rec.${seg.recommendation}`)}</span>
      </div>

      {seg.status === 'NOT_MEASURABLE' ? (
        <p className={styles.muted}>
          {t('cf.engagement', { rounds: seg.periods.map((p) => `${t('cf.round', { n: p.round })}: ${p.engagement ?? 0}`).join(' · ') })}
        </p>
      ) : (
        <>
          {seg.periods.some((p) => p.exposures) && <RoundsChart seg={seg} label={label} />}
          {seg.baseline && seg.recent && (
            <dl className={styles.facts}>
              <div><dt>{t('cf.fresh', { rounds: seg.baseline.rounds.join(', ') })}</dt><dd>{pct(seg.baseline.rate)}</dd></div>
              <div><dt>{t('cf.recent', { rounds: seg.recent.rounds.join(', ') })}</dt><dd>{pct(seg.recent.rate)}</dd></div>
              <div>
                <dt>{t('cf.drop')}</dt>
                <dd>{seg.relative_drop === null ? '—' : pct(seg.relative_drop, 0)}</dd>
                {seg.interval && <small>{t('cf.dropInterval', { lo: signed(seg.interval[0]), hi: signed(seg.interval[1]) })}</small>}
              </div>
            </dl>
          )}
          {sim && (
            <div className={styles.similarity}>
              <span>{t('cf.similarity', { pct: Math.round((sim.total ?? 0) * 100) })}</span>
              <ul>
                {(['copy', 'visual', 'hook', 'offer', 'cta'] as const).filter((k) => sim[k] !== undefined).map((k) => (
                  <li key={k}>{t(`cf.feature.${k}`)} <b>{Math.round((sim[k] ?? 0) * 100)}%</b></li>
                ))}
              </ul>
            </div>
          )}
          {seg.comparator_drops && (seg.comparator_drops.other_variant !== null || seg.comparator_drops.organisation_email !== null) && (
            <p className={styles.muted}>
              {[seg.comparator_drops.other_variant !== null && t('cf.otherVariant', { drop: pct(seg.comparator_drops.other_variant, 0) }),
                seg.comparator_drops.organisation_email !== null && t('cf.orgEmail', { drop: pct(seg.comparator_drops.organisation_email, 0) })]
                .filter(Boolean).join(' · ')}
            </p>
          )}
        </>
      )}

      {alert && (alert.state === 'open' || alert.state === 'refreshing') && (
        <div className={styles.action} data-testid="fatigue-action">
          <p>
            {pending
              ? t(pending.requested_by ? 'cf.pendingPerson' : 'cf.pendingSystem', { strategy: t(`cf.strategy.${pending.strategy}`) })
              : t('cf.noPending')}
          </p>
          {canEdit && (
            <div className={styles.controls}>
              <label className={app.field}>
                <span>{t('cf.strategyLabel')}</span>
                <Select aria-label={t('cf.strategyLabel')} value={strategy} onChange={setStrategy}
                  options={STRATEGIES.map((s) => ({ value: s, label: t(`cf.strategy.${s}`) }))} />
              </label>
              <button type="button" className={`${app.btn} ${app.primary}`} disabled={busy} onClick={refresh}>{t('cf.useRefresh')}</button>
              <input className={app.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('cf.keepNote')} aria-label={t('cf.keepNote')} />
              <button type="button" className={`${app.btn} ${app.ghost}`} disabled={busy} onClick={keep}>{t('cf.keep')}</button>
            </div>
          )}
          <p className={styles.muted}>{t('cf.gates')}</p>
        </div>
      )}

      {record && Object.values(record).some((r) => r.tried > 0) && (
        <p className={styles.muted}>
          {t('cf.learned')}{' '}
          {STRATEGIES.filter((s) => record[s]?.tried).map((s) => t('cf.learnedItem', { strategy: t(`cf.strategy.${s}`), won: record[s].improved, tried: record[s].tried })).join(' · ')}
        </p>
      )}
    </article>
  )
}

/** Creative fatigue: is a repeated concept wearing out? Rates per round, the rule's verdict, refreshes and what they did. */
export default function CreativeFatigue({ report, alerts, interventions, canEdit, onDone }: {
  report: FatigueReport | null
  alerts: FatigueAlert[]
  interventions: CreativeIntervention[]
  canEdit: boolean
  onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  if (!report || !report.result.segments.length) return null
  const segments = report.result.segments
  const done = interventions.filter((i) => i.applied_round !== null || i.outcome === 'CANCELLED')
  return (
    <section className={`${app.panel} ${styles.panel}`} data-testid="creative-fatigue">
      <div className={app.panelHead}>
        <div>
          <h2>{t('cf.title')}</h2>
          <p className={app.panelSub}>{t('cf.sub')}</p>
          <p className={styles.muted}>
            {t('cf.analyzed', { when: new Date(report.analyzed_at).toLocaleString(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }) })}
          </p>
        </div>
      </div>
      <div className={styles.segments}>
        {segments.map((seg) => {
          const alert = alerts.find((a) => a.channel === seg.channel && a.segment === seg.segment && (a.state === 'open' || a.state === 'refreshing'))
          const pending = interventions.find((i) => i.channel === seg.channel && i.segment === seg.segment && i.outcome === 'pending' && i.applied_round === null)
          return <SegmentCard key={`${seg.channel}-${seg.segment}`} seg={seg} alert={alert} pending={pending} canEdit={canEdit} onDone={onDone} />
        })}
      </div>

      {done.length > 0 && (
        <div className={styles.history}>
          <h3>{t('cf.refreshesTitle')}</h3>
          <ul>
            {done.map((i) => (
              <li key={i.id}>
                <strong>{t(`cf.strategy.${i.strategy}`)}</strong>
                {i.applied_round !== null && <> · {t('cf.round', { n: i.applied_round })}</>}
                {' · '}<span className={styles[`out_${i.outcome}`]}>{t(`cf.outcome.${i.outcome}`)}</span>
                {i.outcome_detail?.rate_before !== undefined && i.outcome_detail.rate_after !== undefined && (
                  <small>
                    {t('cf.outcomeDetail', { before: pct(i.outcome_detail.rate_before), after: pct(i.outcome_detail.rate_after),
                      lo: signed(i.outcome_detail.interval?.[0] ?? 0), hi: signed(i.outcome_detail.interval?.[1] ?? 0) })}
                  </small>
                )}
              </li>
            ))}
          </ul>
          <p className={styles.muted}>{t('cf.sequentialNote')}</p>
        </div>
      )}

      {report.result.duplicates.length > 0 && (
        <div className={styles.duplicates}>
          <h3>{t('cf.duplicatesTitle')}</h3>
          <ul>
            {report.result.duplicates.map((d) => (
              <li key={d.round}>{t('cf.duplicate', { round: d.round, of: d.of_round, pct: Math.round((d.similarity.total ?? 0) * 100) })}</li>
            ))}
          </ul>
          <p className={styles.muted}>{t('cf.duplicatesNote')}</p>
        </div>
      )}
    </section>
  )
}
