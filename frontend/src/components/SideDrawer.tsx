import type { ReactNode } from 'react'
import { useEffect, useId, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import css from './SideDrawer.module.css'

/**
 * A sidebar that stays out of the way: closed by default, a slim tab on the
 * screen edge (a floating button on phones) opens it over the page. Esc, the
 * close button or a click outside closes it, and focus returns to the tab.
 */
export default function SideDrawer({
  side,
  label,
  count,
  busy = false,
  open,
  onOpenChange,
  children,
}: {
  side: 'left' | 'right'
  label: string
  count?: number
  busy?: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  const panelId = useId()
  const panelRef = useRef<HTMLElement>(null)
  const handleRef = useRef<HTMLButtonElement>(null)
  const wasOpen = useRef(false)

  useEffect(() => {
    if (open) {
      panelRef.current?.focus()
      const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onOpenChange(false)
      document.addEventListener('keydown', onKey)
      wasOpen.current = true
      return () => document.removeEventListener('keydown', onKey)
    }
    if (wasOpen.current) handleRef.current?.focus()
  }, [open, onOpenChange])

  return (
    <>
      <button
        ref={handleRef}
        type="button"
        className={`${css.handle} ${css[side]}`}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onOpenChange(!open)}
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d={side === 'right' ? 'M15 6l-6 6 6 6' : 'M9 6l6 6-6 6'} stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className={css.handleLabel}>{label}</span>
        {count !== undefined && <span className={`${css.count} ${busy ? css.busy : ''}`}>{count}</span>}
      </button>

      <div className={`${css.backdrop} ${open ? css.backdropOpen : ''}`} onClick={() => onOpenChange(false)} aria-hidden="true" />
      <aside
        ref={panelRef}
        id={panelId}
        className={`${css.panel} ${css[side]} ${open ? css.open : ''}`}
        aria-label={label}
        aria-hidden={!open}
        inert={!open}
        tabIndex={-1}
      >
        <div className={css.head}>
          <h2>{label}</h2>
          <button type="button" className={css.close} onClick={() => onOpenChange(false)} aria-label={t('drawer.close')}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className={css.body}>{children}</div>
      </aside>
    </>
  )
}
