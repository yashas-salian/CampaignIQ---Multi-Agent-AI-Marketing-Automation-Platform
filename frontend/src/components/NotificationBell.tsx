import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import styles from '../styles/app.module.css'
import local from './NotificationBell.module.css'

interface Notice { id: number; kind: string; title: string; body: string | null; link: string | null; created_at: string; read_at: string | null }

const POLL_MS = 60_000

/**
 * The top bar's bell: this person's notifications (a gate waiting for their
 * approval, an overdue approval, a held campaign, paused email...), newest
 * first, with the unread count. Opening one marks it read; the footer turns
 * the matching emails on or off for this person.
 */
export default function NotificationBell() {
  const { t, i18n } = useTranslation()
  const { session } = useSession()
  const [items, setItems] = useState<Notice[]>([])
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState(true)
  const ref = useRef<HTMLDivElement>(null)
  const unread = items.filter((n) => !n.read_at).length

  const load = useCallback(async () => {
    const { data } = await supabase.from('notifications').select('id,kind,title,body,link,created_at,read_at')
      .order('created_at', { ascending: false }).limit(20)
    setItems((data as Notice[]) ?? [])
  }, [])

  useEffect(() => {
    if (!session) return
    load()
    supabase.from('notification_prefs').select('email').maybeSingle().then(({ data }) => setEmail((data as { email: boolean } | null)?.email ?? true))
    const id = window.setInterval(load, POLL_MS)
    const onFocus = () => load()
    window.addEventListener('focus', onFocus)
    return () => {
      window.clearInterval(id)
      window.removeEventListener('focus', onFocus)
    }
  }, [session, load])

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function markRead(ids: number[] | null) {
    await supabase.rpc('mark_notifications_read', { p_ids: ids })
    const now = new Date().toISOString()
    setItems((all) => all.map((n) => (ids === null || ids.includes(n.id) ? { ...n, read_at: n.read_at ?? now } : n)))
  }

  async function toggleEmail(on: boolean) {
    setEmail(on)
    await supabase.rpc('set_notification_email', { p_on: on })
  }

  const when = (iso: string) => new Date(iso).toLocaleString(i18n.language, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

  return (
    <div className={local.wrap} ref={ref}>
      <button type="button" className={`${styles.topbarCell} ${local.bell}`} aria-haspopup="true" aria-expanded={open}
        aria-label={unread ? t('nt.labelUnread', { count: unread }) : t('nt.label')} onClick={() => setOpen((o) => !o)}>
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 16V11a6 6 0 1 1 12 0v5l1.5 2h-15zM10 20a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
        </svg>
        {unread > 0 && <span className={local.badge} data-testid="notification-count">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className={local.panel} role="dialog" aria-label={t('nt.title')}>
          <div className={local.head}>
            <strong>{t('nt.title')}</strong>
            {unread > 0 && <button type="button" className={local.link} onClick={() => markRead(null)}>{t('nt.markAll')}</button>}
          </div>
          {items.length ? (
            <ul className={local.list}>
              {items.map((n) => (
                <li key={n.id} className={n.read_at ? '' : local.unread}>
                  <Link to={n.link ?? '/dashboard'} onClick={() => { if (!n.read_at) markRead([n.id]); setOpen(false) }}>
                    <span className={local.title}>{n.title}</span>
                    {n.body && <span className={local.body}>{n.body}</span>}
                    <span className={local.when}>{when(n.created_at)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <p className={local.empty}>{t('nt.empty')}</p>
          )}
          <label className={local.email}>
            <input type="checkbox" checked={email} onChange={(e) => toggleEmail(e.target.checked)} />
            <span>{t('nt.email')}</span>
          </label>
        </div>
      )}
    </div>
  )
}
