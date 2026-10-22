import { useTranslation } from 'react-i18next'

import { archetypeFor, genderFor } from '../lib/archetypes'
import css from './PersonaFigure.module.css'

/**
 * A persona's 3D character (teacher with books, doctor with a stethoscope, ...)
 * in the persona's own gender. When the gender isn't known it shows initials
 * rather than risk a figure that contradicts the persona.
 */
export default function PersonaFigure({
  archetype,
  gender,
  name,
  demographics,
  psychographics,
  size = 'md',
}: {
  archetype?: unknown
  gender?: unknown
  name?: unknown
  demographics?: unknown
  psychographics?: unknown
  size?: 'md' | 'lg'
}) {
  const { t } = useTranslation()
  const kind = archetypeFor(archetype, name, demographics)
  const sex = genderFor(gender, demographics, psychographics)
  const px = size === 'lg' ? 112 : 64
  const initials = String(name ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join('')
    .toUpperCase()
  return (
    <figure className={`${css.figure} ${size === 'lg' ? css.lg : ''}`}>
      {sex === 'unspecified' ? (
        <span className={css.initials} aria-hidden="true">{initials || '?'}</span>
      ) : (
        <img
          src={`/personas/${kind}-${sex}.webp`}
          alt=""
          loading="lazy"
          decoding="async"
          width={px}
          height={px}
          onError={(e) => {
            // A missing figure falls back to the generic one of the same gender, once.
            const fallback = `/personas/general-${sex}.webp`
            if (!e.currentTarget.src.endsWith(fallback)) e.currentTarget.src = fallback
          }}
        />
      )}
      <figcaption className={css.caption}>{t(`persona.${kind}`)}</figcaption>
    </figure>
  )
}
