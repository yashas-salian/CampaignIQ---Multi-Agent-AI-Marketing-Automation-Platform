import { useEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { DURATION, subscribeToasts, toast, toastSnapshot, type ToastItem, type ToastKind } from '../lib/toast'
import css from './Toaster.module.css'

/** Renders the toasts raised through lib/toast. */
const ICONS: Record<ToastKind, string> = {
  success: 'M5 12.5l4.5 4.5L19 7.5',
  error: 'M12 6.5v7M12 17.5v.01',
  info: 'M12 11v6M12 7v.01',
}

function Toast({ item }: { item: ToastItem }) {
  const { t } = useTranslation()
  const [paused, setPaused] = useState(false)
  const left = useRef(DURATION[item.kind])
  const startedAt = useRef(0)

  // A repeat of the same message restarts the full timer.
  useEffect(() => {
    left.current = DURATION[item.kind]
  }, [item.bump, item.kind])

  // Counts down while visible and not hovered/focused.
  useEffect(() => {
    if (paused) return
    startedAt.current = Date.now()
    const timer = window.setTimeout(() => toast.dismiss(item.id), left.current)
    return () => {
      window.clearTimeout(timer)
      left.current -= Date.now() - startedAt.current
    }
  }, [paused, item.id, item.bump])

  return (
    <li
      className={`${css.toast} ${css[item.kind]} ${paused ? css.paused : ''}`}
      style={{ '--duration': `${DURATION[item.kind]}ms` } as CSSProperties}
      role={item.kind === 'error' ? 'alert' : 'status'}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className={css.icon} aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
          <path d={ICONS[item.kind]} />
        </svg>
      </span>
      <p className={css.text}>{item.text}</p>
      {item.action && (
        <button
          type="button"
          className={css.action}
          onClick={() => {
            toast.dismiss(item.id)
            item.action?.onClick()
          }}
        >
          {item.action.label}
        </button>
      )}
      <button type="button" className={css.close} onClick={() => toast.dismiss(item.id)} aria-label={t('toast.dismiss')}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
      {/* Restarts (via key) when the same message is raised again. */}
      <span key={item.bump} className={css.timer} aria-hidden="true" />
    </li>
  )
}

/** The toast stack: bottom-right on desktop, full width at the bottom on phones. */
export default function Toaster() {
  const { t } = useTranslation()
  const list = useSyncExternalStore(subscribeToasts, toastSnapshot, toastSnapshot)

  // Connection changes are worth telling people about: saves fail while offline.
  useEffect(() => {
    const off = () => toast.info(t('toast.offline'))
    const on = () => toast.success(t('toast.online'))
    window.addEventListener('offline', off)
    window.addEventListener('online', on)
    return () => {
      window.removeEventListener('offline', off)
      window.removeEventListener('online', on)
    }
  }, [t])

  return (
    <ol className={css.stack} aria-label={t('toast.region')}>
      {list.map((item) => (
        <Toast key={item.id} item={item} />
      ))}
    </ol>
  )
}
