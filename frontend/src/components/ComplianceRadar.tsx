import { useTranslation } from 'react-i18next'

import type { GuardrailFlags } from '../lib/types'
import css from './ComplianceRadar.module.css'

const AREAS = ['safety', 'claims', 'readability', 'accessibility'] as const
type Area = (typeof AREAS)[number]

const ICONS: Record<Area, string> = {
  safety: 'M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z',
  claims: 'M5 4h11l3 3v13H5zM9 12l2 2 4-4',
  readability: 'M4 6h16M4 10h16M4 14h10M4 18h7',
  accessibility: 'M12 5a1.5 1.5 0 1 0 0-.01M5 8.5l7 1.5 7-1.5M12 10v4l-3 6M12 14l3 6',
}

/**
 * Brand & compliance radar for one draft: four areas, each clear, to review or
 * blocking, and every finding with a suggested fix. Blocking issues stop a
 * send; the rest is advice for the approver.
 */
export default function ComplianceRadar({ flags, alwaysShow = false }: { flags: GuardrailFlags | null; alwaysShow?: boolean }) {
  const { t } = useTranslation()
  if (!flags) return null
  // Findings saved before the radar existed have no category: they were safety or claims.
  const issues = flags.issues.map((i) => ({ ...i, category: (i.category ?? (i.code === 'claim' ? 'claims' : 'safety')) as Area }))
  if (!alwaysShow && !issues.length && !flags.disclaimer) return null

  const blocked = issues.filter((i) => i.severity === 'block').length
  const toReview = issues.length - blocked
  return (
    <section className={css.radar} aria-label={t('radar.title')}>
      <header className={css.head}>
        <h3>{t('radar.title')}</h3>
        <span className={`${css.overall} ${blocked ? css.bad : toReview ? css.warn : css.good}`}>
          {blocked ? t('radar.blocked', { count: blocked }) : toReview ? t('radar.review', { count: toReview }) : t('radar.clear')}
        </span>
      </header>

      <ul className={css.areas}>
        {AREAS.map((area) => {
          const found = issues.filter((i) => i.category === area)
          const state = found.some((i) => i.severity === 'block') ? 'bad' : found.length ? 'warn' : 'good'
          return (
            <li key={area} className={css[state]}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d={ICONS[area]} stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>{t(`radar.area_${area}`)}</span>
              <b>{state === 'good' ? t('radar.areaClear') : state === 'bad' ? t('radar.areaBlocked') : t('radar.areaReview', { count: found.length })}</b>
            </li>
          )
        })}
      </ul>

      {issues.length > 0 && (
        <ol className={css.findings}>
          {issues.map((i, n) => (
            <li key={n} className={i.severity === 'block' ? css.findingBad : ''}>
              <span className={css.tag}>{i.severity === 'block' ? t('radar.mustFix') : t(`radar.area_${i.category}`)}</span>
              <p>{i.message}</p>
              {i.fix && (
                <p className={css.fix}>
                  <strong>{t('radar.fix')}</strong> {i.fix}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
      {flags.disclaimer && <p className={css.disclaimer}>{t('cd.safetyDisclaimer', { text: flags.disclaimer })}</p>}
    </section>
  )
}
