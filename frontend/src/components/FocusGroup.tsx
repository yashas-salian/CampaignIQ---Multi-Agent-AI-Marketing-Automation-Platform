import type { CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import css from './FocusGroup.module.css'

export interface FocusGroupResult {
  reactions: { name: string; archetype: string; gender: string; reaction: 'click' | 'scroll' | 'object'; likelihood: number; quote: string }[]
  verdict: { click: number; scroll: number; object: number }
  average_likelihood: number
}

/** The personas' reactions to a draft ad, before it's approved: the "audience verdict". */
export default function FocusGroup({ result, compact = false }: { result: FocusGroupResult; compact?: boolean }) {
  const { t } = useTranslation()
  const total = result.reactions.length
  return (
    <section className={`${css.panel} ${compact ? css.compact : ''}`} aria-label={t('fg.title')}>
      <header className={css.head}>
        <div>
          <h3>{t('fg.title')}</h3>
          <p>{t('fg.sub')}</p>
        </div>
        <div className={css.summary}>
          <strong>{t('fg.clicks', { count: result.verdict.click, total })}</strong>
          <span>{t('fg.average', { pct: result.average_likelihood })}</span>
        </div>
      </header>
      <ul className={css.list}>
        {result.reactions.map((r, i) => {
          const figure = r.gender === 'female' || r.gender === 'male' ? `/personas/${r.archetype}-${r.gender}.webp` : null
          return (
            <li key={`${r.name}-${i}`} style={{ '--i': i } as CSSProperties}>
              {figure ? (
                <img className={css.face} src={figure} alt="" loading="lazy" />
              ) : (
                <span className={css.face} aria-hidden="true">{r.name.slice(0, 1).toUpperCase()}</span>
              )}
              <div className={css.body}>
                <div className={css.who}>
                  <strong>{r.name}</strong>
                  <span className={`${css.reaction} ${css[r.reaction]}`}>{t(`fg.r_${r.reaction}`)}</span>
                  <span className={css.meter} title={t('fg.likelihood', { pct: r.likelihood })}>
                    <span style={{ '--w': `${r.likelihood}%` } as CSSProperties} />
                  </span>
                </div>
                {r.quote && <q>{r.quote}</q>}
              </div>
            </li>
          )
        })}
      </ul>
      <p className={css.note}>{t('fg.note')}</p>
    </section>
  )
}
