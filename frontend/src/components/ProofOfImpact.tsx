import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Campaign, Experiment, ImpactArm, ImpactEstimate, ImpactMetric, ImpactResult, ImpactStatus } from '../lib/types'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'
import Select from './Select'
import app from '../styles/app.module.css'
import styles from './ProofOfImpact.module.css'

const pct = (x: number | null | undefined, digits = 1) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(digits)}%`)
const pts = (x: number | null | undefined) => (x === null || x === undefined ? '—' : `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x * 100).toFixed(1)}`)
const num = (x: number | null | undefined, lang: string) => (x === null || x === undefined ? '—' : x.toLocaleString(lang, { maximumFractionDigits: 1 }))

function ago(iso: string | null | undefined, lang: string): string {
  if (!iso) return '—'
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  const fmt = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  if (Math.abs(mins) < 60) return fmt.format(mins, 'minute')
  if (Math.abs(mins) < 1440) return fmt.format(Math.round(mins / 60), 'hour')
  return fmt.format(Math.round(mins / 1440), 'day')
}

/** Units per group to detect `minEffect` over `baseline` (two-sided 5%, 80% power); mirrors impact.sample_size_per_arm. */
function sampleSizePerArm(baseline: number, minEffect: number): number | null {
  const p1 = baseline
  const p2 = baseline + minEffect
  if (!(p1 > 0 && p1 < 1 && p2 > 0 && p2 < 1)) return null
  const pbar = (p1 + p2) / 2
  const n = (1.959963984540054 * Math.sqrt(2 * pbar * (1 - pbar)) + 0.8416212335729143 * Math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (p2 - p1) ** 2
  return Math.ceil(n)
}

// --- The interval chart: one row per comparison or group -------------------------------------

interface IntervalRow {
  key: string
  label: string
  value: number
  lo: number
  hi: number
  tip: string
}

function IntervalChart({ rows, domain, zero, band, format, caption }: {
  rows: IntervalRow[]
  domain: [number, number]
  zero?: boolean
  band?: [number, number]
  format: (x: number) => string
  caption: string
}) {
  const [lo, hi] = domain
  const x = (v: number) => `${((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo)) * 100}%`
  const ticks = [lo, zero ? 0 : (lo + hi) / 2, hi]
  return (
    <figure className={styles.chart} aria-label={caption}>
      {rows.map((r) => (
        <div key={r.key} className={styles.chartRow}>
          <span className={styles.chartLabel}>{r.label}</span>
          <div className={styles.track}>
            {band && <span className={styles.band} style={{ left: x(band[0]), width: `calc(${x(band[1])} - ${x(band[0])})` }} aria-hidden="true" />}
            {zero && <span className={styles.zero} style={{ left: x(0) }} aria-hidden="true" />}
            <span className={styles.whisker} style={{ left: x(r.lo), width: `calc(${x(r.hi)} - ${x(r.lo)})` }} aria-hidden="true" />
            <button type="button" className={styles.dot} style={{ left: x(r.value) }} aria-label={r.tip} data-tip={r.tip} />
          </div>
        </div>
      ))}
      <div className={styles.chartRow} aria-hidden="true">
        <span />
        <div className={styles.axis}>
          {ticks.map((t, i) => (
            <span key={i} style={{ left: x(t) }}>{format(t)}</span>
          ))}
        </div>
      </div>
      <figcaption className={styles.caption}>{caption}</figcaption>
    </figure>
  )
}

// --- The pre-registration form ----------------------------------------------------------------

function Setup({ campaign, experiment, onDone, onCancel }: { campaign: Campaign; experiment: Experiment | null; onDone: () => void; onCancel?: () => void }) {
  const { t, i18n } = useTranslation()
  const ab = !!campaign.ab_test
  const [hypothesis, setHypothesis] = useState(experiment?.hypothesis ?? '')
  const [metric, setMetric] = useState<ImpactMetric>(experiment?.primary_metric ?? 'qualified_signup_rate')
  const [share, setShare] = useState(String(experiment?.control_share ?? 0.2))
  const [windowDays, setWindowDays] = useState(experiment?.attribution_window_days ?? 7)
  const [durationDays, setDurationDays] = useState(experiment?.duration_days ?? 14)
  const [minEffect, setMinEffect] = useState((experiment?.min_effect ?? 0.01) * 100)
  const [baseline, setBaseline] = useState((experiment?.baseline_rate ?? 0.03) * 100)
  const [busy, setBusy] = useState(false)

  const recipients = campaign.email_to?.length ?? 0
  const controlShare = Number(share)
  const noControl = controlShare === 0
  const smallestGroup = Math.floor(recipients * (noControl ? 0.5 : controlShare))
  const needed = sampleSizePerArm(baseline / 100, minEffect / 100)
  const shareOptions = [
    { value: '0.1', label: t('impact.share', { pct: 10 }) },
    { value: '0.2', label: t('impact.share', { pct: 20 }) },
    { value: '0.3', label: t('impact.share', { pct: 30 }) },
    { value: '0.5', label: t('impact.share', { pct: 50 }) },
    ...(ab ? [{ value: '0', label: t('impact.noControl') }] : []),
  ]
  const metricOptions: { value: ImpactMetric; label: string; disabled?: boolean }[] = [
    { value: 'qualified_signup_rate', label: t('impact.metric.qualified_signup_rate') },
    { value: 'conversion_rate', label: t('impact.metric.conversion_rate') },
    { value: 'click_through_rate', label: t('impact.metric.click_through_rate'), disabled: !noControl },
  ]
  const effectiveMetric = !noControl && metric === 'click_through_rate' ? 'qualified_signup_rate' : metric
  const valid = hypothesis.trim().length >= 10 && windowDays >= 1 && windowDays <= 30 && durationDays >= 1 && durationDays <= 90 && minEffect > 0 && minEffect < 100

  async function save() {
    setBusy(true)
    const { error } = await supabase.rpc('declare_experiment', {
      p_campaign: campaign.id, p_hypothesis: hypothesis.trim(), p_metric: effectiveMetric, p_control_share: controlShare,
      p_window_days: windowDays, p_duration_days: durationDays, p_min_units: Math.max(10, Math.min(needed ?? 100, 1000000)),
      p_min_effect: minEffect / 100, p_baseline: baseline > 0 && baseline < 100 ? baseline / 100 : null,
    })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('impact.declaredToast'))
    onDone()
  }

  return (
    <div className={styles.setup}>
      <label className={app.field}>
        <span>{t('impact.hypothesis')}</span>
        <textarea className={app.textarea} rows={2} value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} placeholder={t('impact.hypothesisPlaceholder')} />
      </label>
      <div className={styles.grid}>
        <label className={app.field}>
          <span>{t('impact.primaryMetric')}</span>
          <Select aria-label={t('impact.primaryMetric')} value={effectiveMetric} onChange={setMetric} options={metricOptions} />
        </label>
        <label className={app.field}>
          <span>{t('impact.controlGroup')}</span>
          <Select aria-label={t('impact.controlGroup')} value={share} onChange={setShare} options={shareOptions} />
        </label>
        <label className={app.field}>
          <span>{t('impact.duration')}</span>
          <input type="number" className={app.input} min={1} max={90} value={durationDays} onChange={(e) => setDurationDays(Number(e.target.value))} />
        </label>
        <label className={app.field}>
          <span>{t('impact.window')}</span>
          <input type="number" className={app.input} min={1} max={30} value={windowDays} onChange={(e) => setWindowDays(Number(e.target.value))} />
        </label>
        <label className={app.field}>
          <span>{t('impact.minEffect')}</span>
          <input type="number" className={app.input} min={0.1} max={50} step={0.1} value={minEffect} onChange={(e) => setMinEffect(Number(e.target.value))} />
        </label>
        <label className={app.field}>
          <span>{t('impact.baseline')}</span>
          <input type="number" className={app.input} min={0.1} max={99} step={0.1} value={baseline} onChange={(e) => setBaseline(Number(e.target.value))} />
        </label>
      </div>
      <p className={`${styles.plan} ${needed && smallestGroup < needed ? styles.planShort : ''}`} data-testid="impact-plan">
        {needed
          ? t('impact.plan', { recipients: recipients.toLocaleString(i18n.language), group: smallestGroup.toLocaleString(i18n.language), needed: needed.toLocaleString(i18n.language), effect: minEffect.toFixed(1) })
          : t('impact.planUnknown')}
        {needed && smallestGroup < needed ? ` ${t('impact.planShort')}` : ''}
      </p>
      <p className={styles.muted}>{noControl ? t('impact.abNote') : t('impact.controlNote')}</p>
      <div className={styles.buttons}>
        <button type="button" className={`${app.btn} ${app.primary}`} disabled={busy || !valid} onClick={save}>
          {experiment ? t('impact.update') : t('impact.declare')}
        </button>
        {onCancel && (
          <button type="button" className={`${app.btn} ${app.ghost}`} onClick={onCancel}>
            {t('impact.cancel')}
          </button>
        )}
      </div>
    </div>
  )
}

// --- The impact report ------------------------------------------------------------------------

const TONE: Record<ImpactStatus, string> = {
  COLLECTING: styles.toneNeutral,
  POSITIVE_IMPACT: styles.toneGood,
  NEGATIVE_IMPACT: styles.toneBad,
  NO_MEANINGFUL_IMPACT: styles.toneNeutral,
  INCONCLUSIVE: styles.toneNeutral,
}

function StatusIcon({ status }: { status: ImpactStatus }) {
  const d = {
    COLLECTING: 'M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z',
    POSITIVE_IMPACT: 'M5 13l4 4L19 7',
    NEGATIVE_IMPACT: 'M7 7l10 10M17 7 7 17',
    NO_MEANINGFUL_IMPACT: 'M5 12h14',
    INCONCLUSIVE: 'M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01',
  }[status]
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Report({ experiment, result }: { experiment: Experiment; result: ImpactResult }) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language
  const est = result.estimate
  const arms = (['control', 'treatment', 'treatment_b'] as ImpactArm[]).filter((a) => result.arms[a])
  const armLabel = (a: ImpactArm) => t(`impact.arm.${result.design === 'ab' ? `ab_${a}` : a}`)
  const metricLabel = t(`impact.metric.${result.primary_metric}`)

  const comparisons = useMemo(() => {
    const rows: { key: string; label: string; e: ImpactEstimate }[] = [{ key: 'primary', label: t(result.design === 'ab' ? 'impact.cmpAb' : 'impact.cmpPrimary'), e: est }]
    if (result.secondary?.interval) rows.push({ key: 'secondary', label: t('impact.cmpAb'), e: result.secondary })
    return rows.filter((r) => r.e.interval && r.e.absolute_lift !== null)
  }, [est, result.design, result.secondary, t])
  const extent = Math.max(result.min_effect * 1.6, ...comparisons.flatMap((r) => [Math.abs(r.e.interval![0]), Math.abs(r.e.interval![1])])) * 1.15
  const rateMax = Math.max(0.01, ...arms.map((a) => result.arms[a]!.rate_interval?.[1] ?? 0)) * 1.1

  return (
    <div className={styles.report}>
      <div className={`${styles.verdict} ${TONE[result.status]}`}>
        <span className={styles.verdictIcon}><StatusIcon status={result.status} /></span>
        <div>
          <strong>{t(`impact.status.${result.status}`)}</strong>
          <p>
            {result.final
              ? t(`impact.reason.${result.reason}`, { effect: (result.min_effect * 100).toFixed(1) })
              : t('impact.interimNote', { when: result.window.analysis_at ? new Date(result.window.analysis_at).toLocaleDateString(lang, { day: 'numeric', month: 'short' }) : '—' })}
          </p>
        </div>
        {!result.final && <span className={styles.interimChip}>{t('impact.interim')}</span>}
      </div>

      <section aria-labelledby="impact-causal">
        <h3 id="impact-causal" className={styles.sectionTitle}>
          {t('impact.causalTitle')} <span className={styles.sectionTag}>{t('impact.causalTag')}</span>
        </h3>
        <div className={styles.tiles}>
          <div className={styles.tile}>
            <span>{t('impact.lift', { metric: metricLabel })}</span>
            <strong>{pts(est.absolute_lift)} <small>{t('impact.points')}</small></strong>
            <small>{est.interval ? t('impact.ci', { lo: pts(est.interval[0]), hi: pts(est.interval[1]) }) : '—'}</small>
          </div>
          <div className={styles.tile}>
            <span>{t(result.design === 'ab' ? 'impact.extraB' : 'impact.extra')}</span>
            <strong>{num(est.incremental_successes, lang)}</strong>
            <small>{est.incremental_interval ? t('impact.range', { lo: num(est.incremental_interval[0], lang), hi: num(est.incremental_interval[1], lang) }) : '—'}</small>
          </div>
          <div className={styles.tile}>
            <span>{t(result.design === 'ab' ? 'impact.probB' : 'impact.prob')}</span>
            <strong>{est.prob_treatment_better === null ? '—' : pct(est.prob_treatment_better, 0)}</strong>
            <small>{t('impact.probNote')}</small>
          </div>
          <div className={styles.tile}>
            <span>{t('impact.relative')}</span>
            <strong>{est.relative_lift === null ? '—' : `${est.relative_lift > 0 ? '+' : ''}${(est.relative_lift * 100).toFixed(0)}%`}</strong>
            <small>{est.relative_lift === null ? t('impact.relativeThin') : t('impact.range', { lo: pct(est.relative_interval![0], 0), hi: pct(est.relative_interval![1], 0) })}</small>
          </div>
        </div>
        {comparisons.length > 0 && (
          <IntervalChart
            rows={comparisons.map((r) => ({
              key: r.key, label: r.label, value: r.e.absolute_lift!, lo: r.e.interval![0], hi: r.e.interval![1],
              tip: t('impact.tipLift', { label: r.label, lift: pts(r.e.absolute_lift), lo: pts(r.e.interval![0]), hi: pts(r.e.interval![1]) }),
            }))}
            domain={[-extent, extent]}
            zero
            band={[-result.min_effect, result.min_effect]}
            format={(v) => pts(v)}
            caption={t('impact.chartCaption', { effect: (result.min_effect * 100).toFixed(1) })}
          />
        )}
      </section>

      <section aria-labelledby="impact-observed">
        <h3 id="impact-observed" className={styles.sectionTitle}>
          {t('impact.observedTitle')} <span className={styles.sectionTag}>{t('impact.observedTag')}</span>
        </h3>
        <IntervalChart
          rows={arms.filter((a) => result.arms[a]!.rate !== null && result.arms[a]!.rate_interval).map((a) => {
            const s = result.arms[a]!
            return { key: a, label: armLabel(a), value: s.rate!, lo: s.rate_interval![0], hi: s.rate_interval![1],
                     tip: t('impact.tipRate', { label: armLabel(a), rate: pct(s.rate), lo: pct(s.rate_interval![0]), hi: pct(s.rate_interval![1]), k: s.successes, n: s.units }) }
          })}
          domain={[0, rateMax]}
          format={(v) => pct(v, 1)}
          caption={t('impact.rateCaption', { metric: metricLabel })}
        />
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">{t('impact.group')}</th>
                <th scope="col">{t('impact.units')}</th>
                <th scope="col">{t('impact.emailed')}</th>
                <th scope="col">{t('impact.clicked')}</th>
                <th scope="col">{t('impact.converted')}</th>
                <th scope="col">{metricLabel}</th>
              </tr>
            </thead>
            <tbody>
              {arms.map((a) => {
                const s = result.arms[a]!
                return (
                  <tr key={a}>
                    <th scope="row">{armLabel(a)}</th>
                    <td>{s.units.toLocaleString(lang)}</td>
                    <td>{a === 'control' ? '—' : s.exposed.toLocaleString(lang)}</td>
                    <td>{a === 'control' ? '—' : s.clickers.toLocaleString(lang)}</td>
                    <td>{s.converters.toLocaleString(lang)}</td>
                    <td>{pct(s.rate, 2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      {result.revenue && (
        <section aria-labelledby="impact-revenue">
          <h3 id="impact-revenue" className={styles.sectionTitle}>{t('impact.revenueTitle')}</h3>
          <div className={styles.revenue}>
            <div>
              <span>{t('impact.incrementalRevenue')} <em className={styles.sectionTag}>{t('impact.causalTag')}</em></span>
              <strong>{result.revenue.incremental_revenue === null ? '—' : `${num(result.revenue.incremental_revenue, lang)} ${result.revenue.currency ?? ''}`}</strong>
              <small>{result.revenue.incremental_interval ? t('impact.range', { lo: num(result.revenue.incremental_interval[0], lang), hi: num(result.revenue.incremental_interval[1], lang) }) : t('impact.revenueNoEstimate')}</small>
            </div>
            <div>
              <span>{t('impact.attributedRevenue')} <em className={styles.sectionTagWarn}>{t('impact.notCausal')}</em></span>
              <strong>{`${num(result.revenue.attributed_revenue, lang)} ${result.revenue.currency ?? ''}`}</strong>
              <small>{t('impact.attributionModel', { days: result.window.attribution_window_days })}</small>
            </div>
          </div>
        </section>
      )}

      <section aria-labelledby="impact-quality">
        <h3 id="impact-quality" className={styles.sectionTitle}>{t('impact.qualityTitle')}</h3>
        <ul className={styles.quality}>
          <li className={result.quality.sample_ratio_mismatch ? styles.bad : styles.ok}>
            {result.quality.sample_ratio_mismatch ? t('impact.srmBad') : t('impact.srmOk')}
          </li>
          <li className={result.quality.smallest_group < result.quality.min_units_per_arm ? styles.warn : styles.ok}>
            {t('impact.sampleLine', { n: result.quality.smallest_group.toLocaleString(lang), min: result.quality.min_units_per_arm.toLocaleString(lang) })}
          </li>
          <li className={result.quality.stale_outcomes || result.quality.no_conversions_yet ? styles.warn : styles.ok}>
            {result.quality.no_conversions_yet
              ? t('impact.noConversionsYet')
              : `${t('impact.freshness', { count: result.quality.conversions_received, n: result.quality.conversions_received.toLocaleString(lang) })}${result.quality.last_conversion_at ? ` ${t('impact.lastConversion', { last: ago(result.quality.last_conversion_at, lang) })}` : ''}`}
            {result.quality.stale_outcomes ? ` ${t('impact.stale')}` : ''}
          </li>
          {result.quality.unmatched_conversions > 0 && (
            <li className={styles.warn}>{t('impact.unmatched', { count: result.quality.unmatched_conversions, n: result.quality.unmatched_conversions.toLocaleString(lang) })}</li>
          )}
          <li className={styles.plain}>{t('impact.analyzed', { when: ago(result.analyzed_at, lang) })}</li>
          {result.final && result.bandit && (
            <li className={styles.plain}>{result.bandit.fed ? t('impact.banditFed') : t('impact.banditNotFed')}</li>
          )}
        </ul>
        <details className={styles.details}>
          <summary>{t('impact.assumptionsTitle')}</summary>
          <ul>
            {result.assumptions.map((a) => (
              <li key={a}>{t(`impact.assumption.${a}`, { days: result.window.attribution_window_days })}</li>
            ))}
          </ul>
        </details>
        <details className={styles.details}>
          <summary>{t('impact.designTitle')}</summary>
          <Design experiment={experiment} />
        </details>
      </section>
    </div>
  )
}

function Design({ experiment }: { experiment: Experiment }) {
  const { t, i18n } = useTranslation()
  const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
  return (
    <dl className={styles.design}>
      <div><dt>{t('impact.hypothesis')}</dt><dd>{experiment.hypothesis}</dd></div>
      <div><dt>{t('impact.primaryMetric')}</dt><dd>{t(`impact.metric.${experiment.primary_metric}`)}</dd></div>
      <div><dt>{t('impact.controlGroup')}</dt><dd>{experiment.design === 'ab' ? t('impact.noControl') : t('impact.share', { pct: Math.round(experiment.control_share * 100) })}</dd></div>
      <div><dt>{t('impact.stopRule')}</dt><dd>{t('impact.stopRuleValue', { days: experiment.duration_days, window: experiment.attribution_window_days, min: experiment.min_units_per_arm.toLocaleString(i18n.language), effect: (experiment.min_effect * 100).toFixed(1) })}</dd></div>
      {experiment.started_at && <div><dt>{t('impact.runs')}</dt><dd>{t('impact.runsValue', { start: day(experiment.started_at), end: day(experiment.analysis_at) })}</dd></div>}
      <div><dt>{t('impact.policy')}</dt><dd><code>{experiment.policy_version}</code></dd></div>
    </dl>
  )
}

function Integration({ experiment }: { experiment: Experiment }) {
  const { t } = useTranslation()
  const sample = `POST /functions/v1/api/v1/conversions
Authorization: Bearer mos_...
{ "experiment_id": "${experiment.id}", "event_id": "order-123",
  "token": "<ciq_t from the link>", "qualified": true, "value": 25, "currency": "USD" }`
  return (
    <details className={styles.details}>
      <summary>{t('impact.integrationTitle')}</summary>
      <p className={styles.muted}>{t('impact.integrationBody')}</p>
      <pre className={styles.code}>{sample}</pre>
    </details>
  )
}

/** Proof of impact: declare the experiment before the first email, then read what the campaign caused. */
export default function ProofOfImpact({ campaign, experiment, canEdit, emailSent, onDone }: {
  campaign: Campaign
  experiment: Experiment | null
  canEdit: boolean
  emailSent: boolean
  onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [busy, setBusy] = useState(false)
  const hasAudience = (campaign.email_to?.length ?? 0) > 0
  const finished = ['completed', 'rejected', 'blocked'].includes(campaign.status)
  const canDeclare = canEdit && hasAudience && !emailSent && !finished

  if (!experiment && !canDeclare) return null

  async function withdraw() {
    setBusy(true)
    const { error } = await supabase.rpc('withdraw_experiment', { p_campaign: campaign.id })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('impact.withdrawnToast'))
    onDone()
  }

  return (
    <section className={`${app.panel} ${styles.panel}`} data-testid="proof-of-impact">
      <div className={app.panelHead}>
        <div>
          <h2>{t('impact.title')}</h2>
          <p className={app.panelSub}>{t('impact.sub')}</p>
        </div>
        {experiment && <span className={styles.lockChip}>{experiment.started_at ? t('impact.locked') : t('impact.preregistered')}</span>}
      </div>

      {!experiment && !editing && (
        <div className={styles.empty}>
          <p>{t('impact.emptyBody', { count: campaign.email_to?.length ?? 0, n: (campaign.email_to?.length ?? 0).toLocaleString(i18n.language) })}</p>
          <button type="button" className={`${app.btn} ${app.primary}`} onClick={() => setEditing(true)}>{t('impact.setUp')}</button>
        </div>
      )}
      {editing && (
        <Setup campaign={campaign} experiment={experiment} onDone={() => { setEditing(false); onDone() }} onCancel={() => setEditing(false)} />
      )}
      {experiment && experiment.status === 'declared' && !editing && (
        <div className={styles.declared}>
          <Design experiment={experiment} />
          <p className={styles.muted}>{t('impact.declaredNote')}</p>
          {canDeclare && (
            <div className={styles.buttons}>
              <button type="button" className={`${app.btn} ${app.ghost}`} onClick={() => setEditing(true)}>{t('impact.edit')}</button>
              <button type="button" className={`${app.btn} ${app.ghost}`} disabled={busy} onClick={withdraw}>{t('impact.withdraw')}</button>
            </div>
          )}
        </div>
      )}
      {experiment && experiment.status !== 'declared' && (
        experiment.result ? (
          <Report experiment={experiment} result={experiment.result} />
        ) : (
          <div className={styles.declared}>
            <p className={styles.muted}>{t('impact.notAnalyzed')}</p>
            <Design experiment={experiment} />
          </div>
        )
      )}
      {experiment && experiment.status !== 'declared' && <Integration experiment={experiment} />}
    </section>
  )
}
