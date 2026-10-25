import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import type { CampaignDecision, DecisionOutcome } from '../lib/types'
import styles from './DecisionCard.module.css'

// Reason codes that are good news; the rest are warnings or gaps (src/capabilities/decision.py).
const POSITIVE = new Set(['STRONG_DEMAND', 'RISING_INTEREST', 'STRONG_PURCHASE_INTENT', 'LOW_COMPETITION', 'AUDIENCE_REACHABLE', 'PROVEN_IN_CATEGORY'])
const GAPS = new Set(['MISSING_DEMAND_DATA', 'MISSING_INTENT_DATA', 'MISSING_COMPETITION_DATA', 'MISSING_AUDIENCE', 'NO_HISTORY', 'STALE_EVIDENCE', 'DESTINATION_UNVERIFIED'])

const TONE: Record<DecisionOutcome, string> = {
  LAUNCH: styles.launch,
  TEST_SMALL: styles.test,
  WAIT: styles.wait,
  KILL: styles.kill,
  INSUFFICIENT_EVIDENCE: styles.unknown,
}

/** A small coloured verdict, for lists (Dashboard rows). */
export function DecisionBadge({ decision, blocked }: { decision: DecisionOutcome; blocked?: boolean }) {
  const { t } = useTranslation()
  return (
    <span className={`${styles.badge} ${TONE[decision]}`} title={t(`decision.summary.${blocked ? 'BLOCKED' : decision}`)}>
      {t(`decision.outcome.${blocked ? 'BLOCKED' : decision}`)}
    </span>
  )
}

function ago(iso: string | null | undefined, lang: string): string | null {
  if (!iso) return null
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  const fmt = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  if (Math.abs(mins) < 60) return fmt.format(mins, 'minute')
  if (Math.abs(mins) < 1440) return fmt.format(Math.round(mins / 60), 'hour')
  return fmt.format(Math.round(mins / 1440), 'day')
}

/**
 * The decision engine's recommendation: the verdict and score up top, then
 * why (reason codes), the evidence behind each factor (source, freshness,
 * how reliable it is), any hard block, and what happens next. It recommends;
 * a person still decides at Gate 1.
 */
export default function DecisionCard({ decision, history = [] }: { decision: CampaignDecision; history?: CampaignDecision[] }) {
  const { t, i18n } = useTranslation()
  const blocked = decision.hard_blocks.length > 0
  const verdict = blocked ? 'BLOCKED' : decision.decision
  const reasons = decision.reason_codes.filter((r) => !decision.hard_blocks.some((b) => b.code === r))
  const earlier = history.filter((h) => h.id !== decision.id)

  return (
    <div className={styles.card} data-testid="decision-card">
      <div className={styles.head}>
        <div className={styles.verdictBlock}>
          <span className={styles.eyebrow}>{t('decision.title')}</span>
          <span className={`${styles.verdict} ${TONE[decision.decision]}`}>{t(`decision.outcome.${verdict}`)}</span>
          <p className={styles.summary}>{t(`decision.summary.${verdict}`)}</p>
        </div>
        <div className={styles.numbers}>
          <div className={styles.number}>
            <strong>{decision.opportunity_score ?? '—'}</strong>
            <span>{t('decision.score')}</span>
          </div>
          <div className={styles.number}>
            <strong>{Math.round(decision.uncertainty * 100)}%</strong>
            <span>{t('decision.uncertainty')}</span>
          </div>
        </div>
      </div>

      {blocked && (
        <ul className={styles.blocks} role="alert">
          {decision.hard_blocks.map((b, i) => (
            <li key={i}>
              <strong>{t(`decision.reason.${b.code}`, { defaultValue: b.code })}</strong>
              <span>{b.detail}</span>
            </li>
          ))}
        </ul>
      )}

      {reasons.length > 0 && (
        <div className={styles.section}>
          <h4>{t('decision.why')}</h4>
          <ul className={styles.reasons}>
            {reasons.map((r) => (
              <li key={r} className={POSITIVE.has(r) ? styles.good : GAPS.has(r) ? styles.gap : styles.bad}>
                {t(`decision.reason.${r}`, { defaultValue: r })}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className={styles.section}>
        <h4>{t('decision.evidence')}</h4>
        <ul className={styles.factors}>
          {decision.factors.map((f) => {
            const when = ago(f.fetched_at, i18n.language)
            const state = f.stale ? 'stale' : !f.available || f.score === null ? 'missing' : null
            return (
              <li key={f.key} className={styles.factor}>
                <div className={styles.factorTop}>
                  <span className={styles.factorName}>{t(`decision.factor.${f.key}`)}</span>
                  <span className={styles.weight}>{t('decision.weight', { pct: Math.round(f.weight * 100) })}</span>
                  {state ? (
                    <span className={`${styles.state} ${styles[state]}`}>{t(`decision.${state}`)}</span>
                  ) : (
                    <span className={styles.factorScore}>{Math.round((f.score ?? 0) * 100)}</span>
                  )}
                </div>
                <span className={styles.bar} aria-hidden="true">
                  <span style={{ '--w': `${Math.round((f.score ?? 0) * 100)}%` } as CSSProperties} />
                </span>
                <span className={styles.value}>{f.value}</span>
                <span className={styles.source}>
                  {f.source}
                  {when ? ` · ${when}` : ''}
                  <span className={`${styles.reliability} ${styles[f.reliability]}`} title={t(`decision.reliabilityHint.${f.reliability}`)}>
                    {t(`decision.reliability.${f.reliability}`)}
                  </span>
                </span>
              </li>
            )
          })}
        </ul>
      </div>

      {decision.review_flags.length > 0 && (
        <ul className={styles.flags}>
          {decision.review_flags.map((f, i) => (
            <li key={i}>{f.detail}</li>
          ))}
        </ul>
      )}

      <div className={styles.foot}>
        {decision.constraints.max_rounds && <p>{t('decision.capped', { rounds: decision.constraints.max_rounds })}</p>}
        {decision.reevaluate && (
          <p>{t('decision.reevaluate', { keyword: decision.reevaluate.keyword, threshold: decision.reevaluate.threshold })}</p>
        )}
        {decision.baseline.decision && (
          <p className={styles.muted}>
            {t('decision.baseline', { decision: t(`decision.outcome.${decision.baseline.decision}`) })}
          </p>
        )}
        {earlier.length > 0 && (
          <p className={styles.muted}>
            {t('decision.earlier', {
              list: earlier.map((h) => `${t(`decision.outcome.${h.decision}`)} (${ago(h.created_at, i18n.language) ?? ''})`).join(', '),
            })}
          </p>
        )}
        {decision.outcome && decision.outcome.mean_reward != null && (
          <p>{t('decision.outcomeLine', { rounds: decision.outcome.rounds ?? 0, reward: decision.outcome.mean_reward })}</p>
        )}
        <p className={styles.muted}>{t(blocked ? 'decision.blockedNote' : 'decision.humanNote', { policy: decision.policy_version })}</p>
      </div>
    </div>
  )
}
