import type { CSSProperties } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { AD_SCENE_TEMPLATES, AD_TEMPLATE_FAMILIES, templatePreview } from '../lib/adTemplates'
import styles from '../styles/app.module.css'
import css from './TemplateGallery.module.css'

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
const FAMILY_OF: Record<string, string> = Object.fromEntries(
  Object.entries(AD_TEMPLATE_FAMILIES).flatMap(([family, ids]) => ids.map((id) => [id, family])),
)

/**
 * Every ad template rendered with the same sample product, filterable by
 * family, so a person can pick a layout by eye. Picking one (or "let the AI
 * pick", the empty value) hands it back to the Tools form.
 */
export default function TemplateGallery({
  selected,
  onPick,
  onBack,
}: {
  selected: string
  onPick: (template: string) => void
  onBack: () => void
}) {
  const { t } = useTranslation()
  const [family, setFamily] = useState('all')
  const shown = family === 'all' ? Object.values(AD_TEMPLATE_FAMILIES).flat() : AD_TEMPLATE_FAMILIES[family]

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <button type="button" className={`${css.back} link-wipe`} onClick={onBack}>
            ← {t('tg.back')}
          </button>
          <span className={styles.eyebrow}>{t('tg.eyebrow')}</span>
          <h1 className={styles.title}>{t('tg.title')}</h1>
          <p className={styles.subtitle}>{t('tg.subtitle')}</p>
        </div>
      </header>

      <div className={`${css.intro} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
        <button type="button" className={`${css.auto} ${selected === '' ? css.autoOn : ''}`} aria-pressed={selected === ''} onClick={() => onPick('')}>
          <strong>{t('tg.auto')}</strong>
          <span>{t('tg.autoNote')}</span>
        </button>
        <p className={css.note}>
          {t('tg.sceneNote')} {t('tg.sample')}
        </p>
      </div>

      <div className={`${css.filters} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties} role="radiogroup" aria-label={t('tg.eyebrow')}>
        {['all', ...Object.keys(AD_TEMPLATE_FAMILIES)].map((f) => (
          <button
            key={f}
            type="button"
            role="radio"
            aria-checked={family === f}
            className={`${styles.tab} ${family === f ? styles.tabActive : ''}`}
            onClick={() => setFamily(f)}
          >
            {f === 'all' ? t('tg.all') : t(`tg.family.${f}.name`)}
            <span className={css.count}>{f === 'all' ? Object.values(AD_TEMPLATE_FAMILIES).flat().length : AD_TEMPLATE_FAMILIES[f].length}</span>
          </button>
        ))}
      </div>
      {family !== 'all' && <p className={css.familyDesc}>{t(`tg.family.${family}.desc`)}</p>}

      <ul className={`${css.grid} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
        {shown.map((id) => {
          const on = selected === id
          return (
            <li key={id}>
              <button
                type="button"
                className={`${css.card} ${on ? css.cardOn : ''}`}
                aria-pressed={on}
                aria-label={`${t('tg.use')}: ${humanize(id)}`}
                onClick={() => onPick(id)}
              >
                <span className={css.thumb}>
                  <img src={templatePreview(id)} alt="" loading="lazy" width={480} height={480} />
                </span>
                <strong>{humanize(id)}</strong>
                <span className={css.suits}>{t(`tg.suits.${id}`)}</span>
                <span className={css.tags}>
                  {family === 'all' && <span className={css.tag}>{t(`tg.family.${FAMILY_OF[id]}.name`)}</span>}
                  {AD_SCENE_TEMPLATES.has(id) && <span className={`${css.tag} ${css.scene}`}>{t('tg.scene')}</span>}
                </span>
                <span className={css.use} aria-hidden="true">
                  {on ? `✓ ${t('tg.selected')}` : t('tg.use')}
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
