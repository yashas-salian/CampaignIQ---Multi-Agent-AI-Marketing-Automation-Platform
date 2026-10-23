import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'

import { isLoading, subscribeLoading, usePageLoading } from '../lib/loading'
import LoaderMascot from './LoaderMascot'
import css from './PageLoader.module.css'

const SHOW_AFTER = 150 // fast loads never flash the overlay
const MIN_VISIBLE = 400 // once shown, long enough not to flicker
const STEPS = ['score', 'personas', 'creative', 'measure'] as const

/** Renders nothing; keeps the page loader up while mounted (route / auth waits). */
export function LoadingMarker() {
  usePageLoading(true)
  return null
}

/** The caption walks through what the product does while you wait. */
function Caption() {
  const { t } = useTranslation()
  const [i, setI] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => setI((n) => (n + 1) % STEPS.length), 1400)
    return () => window.clearInterval(id)
  }, [])
  return (
    <span className={css.caption}>
      <span key={i} className={css.step}>
        {t(`loader.${STEPS[i]}`)}
      </span>
    </span>
  )
}

/** Frosted overlay with the animated mascot while a page is loading. */
export default function PageLoader() {
  const { t } = useTranslation()
  const loading = useSyncExternalStore(subscribeLoading, isLoading, isLoading)
  const [visible, setVisible] = useState(false)
  const shownAt = useRef(0)

  useEffect(() => {
    if (loading) {
      const timer = window.setTimeout(() => {
        shownAt.current = Date.now()
        setVisible(true)
      }, SHOW_AFTER)
      return () => window.clearTimeout(timer)
    }
    if (!visible) return
    const wait = Math.max(0, MIN_VISIBLE - (Date.now() - shownAt.current))
    const timer = window.setTimeout(() => setVisible(false), wait)
    return () => window.clearTimeout(timer)
  }, [loading, visible])

  return (
    <div className={`${css.overlay} ${visible ? css.shown : ''}`} aria-hidden={!visible} data-page-loader="">
      {visible && (
        <div className={css.card} role="status" aria-label={t('common.loading')}>
          <LoaderMascot />
          <Caption />
        </div>
      )}
    </div>
  )
}
