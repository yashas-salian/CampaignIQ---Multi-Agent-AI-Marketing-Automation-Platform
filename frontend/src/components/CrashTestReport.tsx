import { useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { CrashAd, CrashFinding, CrashReport, CrashRisk, CrashTestRow } from '../lib/types'
import { toast } from '../lib/toast'
import { useWorkerRun } from '../lib/workerRun'
import app from '../styles/app.module.css'
import styles from './CrashTestReport.module.css'

const TONE: Record<CrashRisk, string> = {
  clear: styles.clear,
  low: styles.low,
  medium: styles.medium,
  high: styles.high,
  critical: styles.critical,
}

/** A regex for the quoted words in the ad, forgiving hyphen and quote-mark styles (like the backend's locate()). */
function quotePattern(quote: string): RegExp | null {
  const words = quote.trim()
  if (words.length < 3) return null
  const escaped = words
    .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    .replace(/[-‐-―−]/g, '[-\\u2010-\\u2015\\u2212]')
    .replace(/['‘’]/g, "['\\u2018\\u2019]")
    .replace(/\s+/g, '\\s+')
  return new RegExp(escaped, 'i')
}

/** The ad's text with the quoted problems marked in their severity's colour. */
function Marked({ text, findings }: { text: string; findings: CrashFinding[] }) {
  const parts: ReactNode[] = []
  let rest = text
  let key = 0
  // Walk left to right, marking the earliest remaining quote each time.
  for (;;) {
    let best: { index: number; length: number; finding: CrashFinding } | null = null
    for (const f of findings) {
      const re = f.quote ? quotePattern(f.quote) : null
      const m = re ? re.exec(rest) : null
      if (m && (!best || m.index < best.index)) best = { index: m.index, length: m[0].length, finding: f }
    }
    if (!best) break
    if (best.index > 0) parts.push(rest.slice(0, best.index))
    parts.push(
      <mark key={key++} className={`${styles.mark} ${TONE[best.finding.severity]}`} title={best.finding.problem}>
        {rest.slice(best.index, best.index + best.length)}
      </mark>,
    )
    rest = rest.slice(best.index + best.length)
  }
  parts.push(rest)
  return <>{parts}</>
}

function AdPreview({ ad, findings, label }: { ad: CrashAd; findings: CrashFinding[]; label: string }) {
  const { t } = useTranslation()
  const of = (field: CrashFinding['field']) => findings.filter((f) => f.field === field)
  return (
    <div className={styles.ad}>
      <span className={styles.adLabel}>{label}</span>
      {ad.headline && (
        <p className={styles.adHeadline}>
          <Marked text={ad.headline} findings={of('headline')} />
        </p>
      )}
      <p className={styles.adBody}>
        <Marked text={ad.body} findings={of('body')} />
      </p>
      {ad.cta && (
        <span className={styles.adCta} aria-label={t('crash.button')}>
          <Marked text={ad.cta} findings={of('cta')} />
        </span>
      )}
    </div>
  )
}

function FindingItem({ f, status }: { f: CrashFinding; status?: 'resolved' | 'remaining' | 'new' }) {
  const { t } = useTranslation()
  return (
    <li className={styles.finding}>
      <div className={styles.findingTop}>
        <span className={`${styles.sev} ${TONE[f.severity]}`}>{t(`crash.severity.${f.severity}`)}</span>
        <strong>{t(`crash.type.${f.type}`, { defaultValue: f.type })}</strong>
        {f.scenario && <span className={styles.scenario}>{t(`crash.scenario.${f.scenario}`, { defaultValue: f.scenario })}</span>}
        {status && <span className={`${styles.status} ${styles[status]}`}>{t(`crash.${status}`)}</span>}
      </div>
      {f.quote && <q className={styles.quote}>{f.quote}</q>}
      <p>{f.problem}</p>
      {f.fix && <p className={styles.fix}>{t('crash.fixLabel')} {f.fix}</p>}
    </li>
  )
}

function Findings({ findings, statusOf }: { findings: CrashFinding[]; statusOf?: (f: CrashFinding) => 'resolved' | 'remaining' | 'new' | undefined }) {
  const { t } = useTranslation()
  const rules = findings.filter((f) => f.source === 'rule')
  const simulated = findings.filter((f) => f.source === 'simulation')
  return (
    <div className={styles.columns}>
      <div className={styles.group}>
        <h4>
          {t('crash.rules')} <span className={styles.groupNote}>{t('crash.rulesNote')}</span>
        </h4>
        {rules.length ? <ul className={styles.list}>{rules.map((f) => <FindingItem key={f.key} f={f} status={statusOf?.(f)} />)}</ul> : <p className={styles.none}>{t('crash.noRuleFindings')}</p>}
      </div>
      <div className={styles.group}>
        <h4>
          {t('crash.simulated')} <span className={styles.groupNote}>{t('crash.simulatedNote')}</span>
        </h4>
        {simulated.length ? <ul className={styles.list}>{simulated.map((f) => <FindingItem key={f.key} f={f} status={statusOf?.(f)} />)}</ul> : <p className={styles.none}>{t('crash.noSimFindings')}</p>}
      </div>
    </div>
  )
}

/**
 * The crash test's risk report: the ad with each problem marked, the rule
 * checks and simulated scenarios that found them, and (when anything was high
 * or critical) a revised version re-tested on the same scenarios, with what it
 * resolved. On a campaign at Gate 2, approvers can use the revision or re-run
 * the test; the simulator never approves anything itself.
 */
export default function CrashTestReport({
  test,
  report: bare,
  campaignId,
  round,
  canAct = false,
  onChanged,
}: {
  test?: CrashTestRow
  report?: CrashReport
  campaignId?: string
  round?: number
  canAct?: boolean
  onChanged?: () => void
}) {
  const { t } = useTranslation()
  const report = (test?.report ?? bare) as CrashReport
  const applied = !!test?.applied_at
  const [applying, apply] = useWorkerRun((ok, error) => {
    if (ok) toast.success(t('crash.appliedToast'))
    else toast.error(t('crash.failedToast', { message: error ?? '' }))
    onChanged?.()
  })
  const [rerunning, rerun] = useWorkerRun((ok, error) => {
    if (ok) toast.success(t('crash.rerunToast'))
    else toast.error(t('crash.failedToast', { message: error ?? '' }))
    onChanged?.()
  })
  const comparison = report.comparison
  const statusOf = useMemo(() => {
    if (!comparison) return undefined
    const resolved = new Set(comparison.resolved)
    return (f: CrashFinding) => (resolved.has(f.key) ? 'resolved' : undefined)
  }, [comparison])
  const revisedStatus = useMemo(() => {
    if (!comparison) return undefined
    const fresh = new Set(comparison.new)
    return (f: CrashFinding) => (fresh.has(f.key) ? 'new' : 'remaining')
  }, [comparison])

  const effective: CrashRisk = applied && test?.revised_risk ? test.revised_risk : report.risk
  const total = report.findings.length

  async function start(kind: 'apply' | 'rerun') {
    if (!campaignId || round === undefined) return
    const error =
      kind === 'apply'
        ? await apply('apply_revision', { campaign_id: campaignId, round, crash_test_id: test?.id })
        : await rerun('crash_test', { campaign_id: campaignId, round })
    if (error) toast.error(t('crash.failedToast', { message: error }))
  }

  return (
    <div className={styles.card} data-testid="crash-test">
      <div className={styles.head}>
        <div className={styles.titleBlock}>
          <span className={styles.eyebrow}>{t('crash.title')}</span>
          <div className={styles.verdictRow}>
            <span className={`${styles.verdict} ${TONE[effective]}`}>{t(`crash.risk.${effective}`)}</span>
            <span className={styles.simTag}>{t('crash.simulationTag')}</span>
          </div>
          <p className={styles.summary}>{t(`crash.summary.${effective}`, { count: total })}</p>
        </div>
        <ul className={styles.counts} aria-label={t('crash.countsLabel')}>
          {(['critical', 'high', 'medium', 'low'] as const).map((s) => (
            <li key={s} className={TONE[s]}>
              <strong>{report.counts?.[s] ?? 0}</strong>
              <span>{t(`crash.severity.${s}`)}</span>
            </li>
          ))}
        </ul>
      </div>

      {report.note && <p className={styles.note}>{report.note}</p>}

      {/* With a revision, the ad is shown once, as "Before" next to "After". */}
      {!report.revised && <AdPreview ad={report.ad} findings={report.findings} label={t('crash.theAd')} />}
      <Findings findings={report.findings} statusOf={statusOf} />

      {report.revised && (
        <section className={styles.revision} aria-label={t('crash.revisionTitle')}>
          <div className={styles.revisionHead}>
            <h4>{t('crash.revisionTitle')}</h4>
            {comparison && (
              <span className={styles.tally}>
                {t('crash.tally', { resolved: comparison.resolved.length, remaining: comparison.remaining.length, fresh: comparison.new.length })}
              </span>
            )}
            {report.revised_risk && <span className={`${styles.verdict} ${styles.small} ${TONE[report.revised_risk]}`}>{t(`crash.risk.${report.revised_risk}`)}</span>}
          </div>
          <div className={styles.compare}>
            <AdPreview ad={report.ad} findings={report.findings} label={t('crash.before')} />
            <AdPreview ad={report.revised} findings={report.revised_findings} label={t('crash.after')} />
          </div>
          {report.revision_notes.length > 0 && (
            <ul className={styles.notes}>
              {report.revision_notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          )}
          {report.revised_findings.length > 0 && <Findings findings={report.revised_findings} statusOf={revisedStatus} />}
          {test && canAct && (
            <div className={styles.actions}>
              {applied ? (
                <span className={styles.applied}>{t('crash.applied')}</span>
              ) : (
                <button type="button" className={`${app.btn} ${app.primary}`} disabled={applying} onClick={() => start('apply')}>
                  {applying && <span className={app.spinner} aria-hidden="true" />}
                  {applying ? t('crash.applying') : t('crash.apply')}
                </button>
              )}
              <span className={styles.muted}>{t('crash.applyHint')}</span>
            </div>
          )}
        </section>
      )}

      <div className={styles.foot}>
        {test && canAct && (
          <button type="button" className={`${app.btn} ${app.ghost}`} disabled={rerunning} onClick={() => start('rerun')}>
            {rerunning && <span className={app.spinner} aria-hidden="true" />}
            {rerunning ? t('crash.rerunning') : t('crash.rerun')}
          </button>
        )}
        <p className={styles.muted}>{t('crash.footer', { set: report.scenario_set, rules: report.rules_version })}</p>
      </div>
    </div>
  )
}
