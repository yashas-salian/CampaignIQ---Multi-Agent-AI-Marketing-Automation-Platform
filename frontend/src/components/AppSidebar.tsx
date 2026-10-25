import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useLocation } from 'react-router-dom'

import { setDrawerOpen, useShell } from '../lib/shell'
import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import css from './AppSidebar.module.css'

const OPEN_DELAY = 80 // brushing past the edge doesn't flash it open
const CLOSE_DELAY = 220

const ICONS: Record<string, ReactNode> = {
  new: <path d="M12 5v14M5 12h14" />,
  dashboard: <path d="M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z" />,
  calendar: <path d="M4 6h16v14H4zM4 10h16M9 3v4M15 3v4" />,
  tools: <path d="M14 6a4 4 0 0 1-5.3 5.3L4 16l4 4 4.7-4.7A4 4 0 0 1 18 10l-2.5-.5L15 7z" />,
  history: <path d="M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4M12 8v4l3 2" />,
  competitors: <path d="M3 20h18M6 16V9M11 16V5M16 16v-5M20 7l-4 4-5-6-5 4" />,
  playbooks: <path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3zM5 17a3 3 0 0 1 3-3h10M9 8h5" />,
  model: <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9zM12 12l8-4.5M12 12v9M12 12L4 7.5" />,
  settings: <path d="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3.9a7 7 0 0 0-2.1-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2.1 1.2l-2.3-.9-2 3.4 2 1.5a7 7 0 0 0 0 2.4l-2 1.5 2 3.4 2.3-.9a7 7 0 0 0 2.1 1.2L10 21h4l.5-2.6a7 7 0 0 0 2.1-1.2l2.3.9 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z" />,
  admin: <path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6zM9 12l2 2 4-4" />,
  docs: <path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h7M9 17h5" />,
  status: <path d="M3 12h4l3-7 4 14 3-7h4" />,
  contact: <path d="M4 6h16v10H8l-4 4zM8 10h8" />,
}

function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  )
}

/**
 * The app's main navigation, on the left of every signed-in page. Desktop: a
 * slim icon rail that slides out to full labels when the cursor (or keyboard
 * focus) reaches the left edge. Phones: the same list as a drawer, opened from
 * the top bar's menu button. On Settings it also lists that page's sections,
 * with the one in view marked.
 */
export default function AppSidebar() {
  const { t } = useTranslation()
  const { pathname, hash } = useLocation()
  const { drawerOpen, settings } = useShell()
  const { active, can } = useOrg()
  // Only links this person can use: viewers and approvers can't start campaigns.
  const canCreate = !!active && can('create', active.id)
  const [expanded, setExpanded] = useState(false)
  const [isAdmin, setIsAdmin] = useState(false)
  const timer = useRef(0)
  const nav = useRef<HTMLElement>(null)

  useEffect(() => {
    supabase.rpc('is_platform_admin').then(({ data }) => setIsAdmin(Boolean(data)))
  }, [])

  // A new page closes it (desktop and phone).
  useEffect(() => {
    setExpanded(false)
    setDrawerOpen(false)
  }, [pathname, hash])

  useEffect(() => {
    if (!drawerOpen && !expanded) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      setExpanded(false)
      setDrawerOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [drawerOpen, expanded])

  const later = (open: boolean, delay: number) => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setExpanded(open), delay)
  }

  const item = (to: string, icon: string, label: string, end = false) => (
    <NavLink to={to} end={end} className={({ isActive }) => `${css.item} wipe-host ${isActive ? css.active : ''}`} title={label}>
      <Icon name={icon} />
      <span className={`${css.label} link-wipe`}>{label}</span>
    </NavLink>
  )

  const open = expanded || drawerOpen
  return (
    <>
      <div className={`${css.backdrop} ${drawerOpen ? css.backdropOpen : ''}`} onClick={() => setDrawerOpen(false)} aria-hidden="true" />
      <nav
        ref={nav}
        className={`${css.sidebar} ${open ? css.open : ''} ${drawerOpen ? css.drawer : ''}`}
        aria-label={t('nav.main')}
        onMouseEnter={() => later(true, OPEN_DELAY)}
        onMouseLeave={() => later(false, CLOSE_DELAY)}
        onFocus={() => later(true, 0)}
        onBlur={(e) => {
          if (!nav.current?.contains(e.relatedTarget as Node)) later(false, 0)
        }}
      >
        {canCreate && (
          <Link to="/dashboard#new" className={`${css.item} ${css.create}`} title={t('dash.newCampaign')}>
            <Icon name="new" />
            <span className={css.label}>{t('dash.newCampaign')}</span>
          </Link>
        )}

        <p className={css.group}>{t('nav.workspace')}</p>
        {item('/dashboard', 'dashboard', t('common.dashboard'))}
        {item('/calendar', 'calendar', t('cal.nav'))}
        {item('/tools', 'tools', t('common.tools'), true)}
        {item('/tools/history', 'history', t('hist.title'))}

        <p className={css.group}>{t('nav.insights')}</p>
        {item('/competitors', 'competitors', t('ci.nav'))}
        {item('/playbooks', 'playbooks', t('pb.nav'))}
        {item('/models', 'model', t('mc.nav'))}

        <p className={css.group}>{t('nav.account')}</p>
        {item('/settings', 'settings', t('common.settings'))}
        {settings && pathname.startsWith('/settings') && (
          <ul className={css.sub} aria-label={t('st.sections')}>
            {settings.sections.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={`wipe-host ${s.id === settings.current ? css.subCurrent : ''}`}
                  aria-current={s.id === settings.current ? 'location' : undefined}
                  onClick={() => {
                    settings.pick(s.id)
                    setDrawerOpen(false)
                  }}
                >
                  <span className="link-wipe">{s.label}</span>
                </a>
              </li>
            ))}
          </ul>
        )}
        {isAdmin && item('/admin', 'admin', t('admin.title'))}

        <div className={css.foot}>
          <p className={css.group}>{t('nav.help')}</p>
          {item('/docs', 'docs', t('nav.docs'))}
          {item('/status', 'status', t('nav.status'))}
          {item('/contact', 'contact', t('nav.contact'))}
        </div>
      </nav>
    </>
  )
}
