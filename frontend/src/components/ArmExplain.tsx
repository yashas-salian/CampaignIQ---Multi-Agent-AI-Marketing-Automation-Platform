import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import css from './ArmExplain.module.css'

export interface ArmView {
  arm_index: number
  image_style: string
  copy_tone: string
  expected: number
  bonus: number
  score: number
  pulls: number
  mean_reward: number | null
}
export interface ArmExplanation {
  algorithm: string
  context: { age_bracket: string; income_tier: string; domain_category: string; channels: string[] }
  chosen: ArmView
  mode: 'exploit' | 'explore'
  rank: number
  alternatives: ArmView[]
  arms_tried: number
  total_rounds: number
}

const human = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/**
 * "Why this ad?": the learning loop's reasoning for one round. Each bar splits
 * an option's score into evidence (what past rounds showed) and exploration
 * (how much is still unknown), so you can see whether it played safe or tried
 * something new.
 */
export default function ArmExplain({ explain }: { explain: ArmExplanation }) {
  const { t } = useTranslation()
  const rows = [explain.chosen, ...explain.alternatives]
  const max = Math.max(0.01, ...rows.map((r) => Math.max(0, r.expected) + r.bonus))
  const c = explain.chosen
  const label = (v: ArmView) => `${human(v.image_style)} × ${human(v.copy_tone).toLowerCase()}`

  return (
    <details className={css.why}>
      <summary>
        <span className={css.spark} aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <path d="M12 3v3M12 18v3M3 12h3M18 12h3M6 6l2 2M16 16l2 2M6 18l2-2M16 8l2-2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
        </span>
        {t('why.title')}
        <span className={`${css.mode} ${explain.mode === 'explore' ? css.explore : ''}`}>{t(`why.mode_${explain.mode}`)}</span>
      </summary>

      <p className={css.lead}>
        {explain.mode === 'exploit'
          ? t('why.exploit', { arm: label(c), rounds: c.pulls, mean: c.mean_reward?.toFixed(2) ?? '—' })
          : t('why.explore', { arm: label(c) })}
      </p>

      <ul className={css.bars}>
        {rows.map((r) => (
          <li key={r.arm_index} className={r.arm_index === c.arm_index ? css.chosen : ''}>
            <span className={css.armLabel}>
              {label(r)}
              {r.arm_index === c.arm_index && <b>{t('why.picked')}</b>}
            </span>
            <span className={css.track} title={t('why.barTitle', { evidence: r.expected.toFixed(2), bonus: r.bonus.toFixed(2) })}>
              <span className={css.evidence} style={{ '--w': `${(Math.max(0, r.expected) / max) * 100}%` } as CSSProperties} />
              <span className={css.bonus} style={{ '--w': `${(r.bonus / max) * 100}%` } as CSSProperties} />
            </span>
            <span className={css.pulls}>{t('why.pulls', { count: r.pulls })}</span>
          </li>
        ))}
      </ul>
      <p className={css.legend}>
        <span><i className={css.keyEvidence} />{t('why.evidence')}</span>
        <span><i className={css.keyBonus} />{t('why.bonus')}</span>
      </p>

      <p className={css.foot}>
        {t('why.foot', {
          rank: explain.rank,
          audience: [explain.context.age_bracket, t('why.income', { tier: explain.context.income_tier }), human(explain.context.domain_category), explain.context.channels.join(' + ')].join(' · '),
          rounds: explain.total_rounds,
          tried: explain.arms_tried,
        })}
      </p>
    </details>
  )
}
