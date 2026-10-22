import { useTranslation } from 'react-i18next'

import { archetypeFor } from '../lib/archetypes'
import css from './PersonaFigure.module.css'

/** A persona's 3D character (teacher with books, doctor with a stethoscope, ...). */
export default function PersonaFigure({
  archetype,
  name,
  demographics,
  size = 'md',
}: {
  archetype?: unknown
  name?: unknown
  demographics?: unknown
  size?: 'md' | 'lg'
}) {
  const { t } = useTranslation()
  const kind = archetypeFor(archetype, name, demographics)
  return (
    <figure className={`${css.figure} ${size === 'lg' ? css.lg : ''}`}>
      <img
        src={`/personas/${kind}.webp`}
        alt=""
        loading="lazy"
        decoding="async"
        width={size === 'lg' ? 112 : 64}
        height={size === 'lg' ? 112 : 64}
        onError={(e) => {
          // A missing figure falls back to the generic one, once.
          if (!e.currentTarget.src.endsWith('/general.webp')) e.currentTarget.src = '/personas/general.webp'
        }}
      />
      <figcaption className={css.caption}>{t(`persona.${kind}`)}</figcaption>
    </figure>
  )
}
