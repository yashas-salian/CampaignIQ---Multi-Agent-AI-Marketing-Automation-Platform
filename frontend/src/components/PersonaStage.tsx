import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { archetypeFor, genderFor } from '../lib/archetypes'
import css from './PersonaStage.module.css'

const Persona3D = lazy(() => import('./Persona3D'))

// One check per model file per session. The SPA host answers unknown paths
// with index.html (200), so "exists" means a non-HTML response.
const known = new Map<string, Promise<boolean>>()
function modelExists(url: string) {
  if (!known.has(url)) {
    known.set(
      url,
      fetch(url, { method: 'HEAD' })
        .then((r) => r.ok && !(r.headers.get('content-type') ?? '').includes('text/html'))
        .catch(() => false),
    )
  }
  return known.get(url)!
}

/**
 * The persona's figure, standing above its info card: a rotatable 3D model
 * when one has been made (frontend/scripts/make_persona_models.py), the 2D
 * figure until then, and initials when the persona's gender isn't known.
 */
export default function PersonaStage({
  archetype,
  gender,
  name,
  demographics,
  psychographics,
}: {
  archetype?: unknown
  gender?: unknown
  name?: unknown
  demographics?: unknown
  psychographics?: unknown
}) {
  const { t } = useTranslation()
  const kind = archetypeFor(archetype, name, demographics)
  const sex = genderFor(gender, demographics, psychographics)
  const figure = `${kind}-${sex}`
  const modelUrl = `/personas/models/${figure}.glb`
  const [has3D, setHas3D] = useState(false)
  const onFail = useCallback(() => setHas3D(false), [])

  useEffect(() => {
    if (sex === 'unspecified') return
    let live = true
    modelExists(modelUrl).then((ok) => live && setHas3D(ok))
    return () => {
      live = false
    }
  }, [modelUrl, sex])

  const role = t(`persona.${kind}`)
  if (sex === 'unspecified') {
    const initials = String(name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0])
      .join('')
      .toUpperCase()
    return (
      <div className={css.stage}>
        <span className={css.initials} aria-hidden="true">{initials || '?'}</span>
      </div>
    )
  }

  const still = <img className={css.still} src={`/personas/${figure}.webp`} alt="" loading="lazy" decoding="async" />
  return (
    <div className={css.stage}>
      {has3D ? (
        <Suspense fallback={still}>
          <Persona3D src={modelUrl} label={t('persona.figure3d', { role })} onFail={onFail} />
        </Suspense>
      ) : (
        still
      )}
      {has3D && <span className={css.hint}>{t('persona.dragHint')}</span>}
    </div>
  )
}
