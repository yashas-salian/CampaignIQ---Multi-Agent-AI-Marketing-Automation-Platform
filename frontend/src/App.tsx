import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { UI_LOCALES } from './i18n'
import LogoMark from './components/LogoMark'
import { displayName } from './lib/profile'
import { ThemeProvider } from './lib/ThemeContext'
import { supabase } from './lib/supabaseClient'
import { useSession } from './lib/useAuth'
import { useTheme } from './lib/useTheme'
import Landing from './pages/Landing'
import Login from './pages/Login'
import styles from './styles/shell.module.css'

// Logged-in pages load on demand, so a first-time visitor to the public
// Landing page doesn't download the whole app.
const CampaignDetail = lazy(() => import('./pages/CampaignDetail'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Metrics = lazy(() => import('./pages/Metrics'))
const Settings = lazy(() => import('./pages/Settings'))
const Tools = lazy(() => import('./pages/Tools'))
// Secondary public pages, also on demand.
const About = lazy(() => import('./pages/About'))
const Contact = lazy(() => import('./pages/Contact'))
const Privacy = lazy(() => import('./pages/Privacy'))
const Terms = lazy(() => import('./pages/Terms'))
const NotFound = lazy(() => import('./pages/NotFound'))

/** New page → start at the top, unless the link targets a section (#hash). */
function ScrollToTop() {
  const { pathname, hash } = useLocation()
  useEffect(() => {
    if (!hash) window.scrollTo({ top: 0, left: 0, behavior: 'instant' })
  }, [pathname, hash])
  return null
}

/** Lazy public pages show nothing while loading; their own entrance animation covers it. */
function Lazy({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  const { t } = useTranslation()
  const fallback = <p className={`p-8 ${styles.muted}`}>{t('common.loading')}</p>
  if (loading) return fallback
  if (!session) return <Navigate to="/login" replace />
  return <Suspense fallback={fallback}>{children}</Suspense>
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  return (
    <button className={`${styles.topbarCell} ${styles.themeToggle}`} aria-label="Toggle color theme" onClick={toggleTheme}>
      {theme === 'light' ? (
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z" stroke="currentColor" strokeWidth="1.8" />
          <path
            d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" fill="none">
          <path
            d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.4 5.4 0 0 1 12 3z"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </button>
  )
}

// The app bar belongs to the logged-in app only; public pages (and the 404)
// render their own header even for a logged-in visitor.
const APP_PREFIXES = ['/dashboard', '/campaigns', '/tools', '/settings']

/**
 * Username cell with a dropdown (account email, Settings, Sign out). Opens on
 * hover, on keyboard focus, and on tap for touch screens; Esc or an outside
 * click closes it.
 */
function AccountMenu({ name, email }: { name: string | null; email: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

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

  return (
    <div ref={ref} className={`${styles.account} ${open ? styles.accountOpen : ''}`} onMouseLeave={() => setOpen(false)}>
      <button
        type="button"
        className={`${styles.topbarCell} ${styles.accountButton} wipe-host`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span className={styles.avatar} aria-hidden="true">
          {(name ?? email).trim().charAt(0).toUpperCase() || '?'}
        </span>
        <span className="link-wipe">{name ?? t('dash.addUsername')}</span>
        <svg className={styles.chevron} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <div className={styles.menu} role="menu">
        <p className={styles.menuEmail}>{email}</p>
        <Link role="menuitem" to="/settings#account" className={styles.menuItem} onClick={() => setOpen(false)}>
          {t('common.settings')}
        </Link>
        <button role="menuitem" type="button" className={`${styles.menuItem} ${styles.menuDanger}`} onClick={() => supabase.auth.signOut()}>
          {t('st.signOut')}
        </button>
      </div>
    </div>
  )
}

function TopBar() {
  const { session } = useSession()
  const { t, i18n } = useTranslation()
  const { pathname } = useLocation()
  if (!session || !APP_PREFIXES.some((p) => pathname.startsWith(p))) return null
  // Same segmented tile bar as the Landing page nav.
  return (
    <header className={styles.topbar}>
      <Link to="/dashboard" className={`${styles.topbarCell} ${styles.topbarBrand}`}>
        <LogoMark className={styles.topbarLogo} />
        MarketingOS
      </Link>
      <nav className={styles.topbarLinks}>
        {(
          [
            ['/dashboard', t('common.dashboard')],
            ['/tools', t('common.tools')],
            ['/settings', t('common.settings')],
          ] as const
        ).map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => `${styles.topbarCell} wipe-host ${isActive ? styles.topbarActive : ''}`}>
            <span className="link-wipe">{label}</span>
          </NavLink>
        ))}
      </nav>
      <div className={styles.topbarLinks}>
        <label className={styles.topbarCell}>
          <span className="sr-only">Language</span>
          <select value={i18n.language} onChange={(e) => i18n.changeLanguage(e.target.value)} className={styles.topbarSelect}>
            {UI_LOCALES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <ThemeToggle />
        <AccountMenu name={displayName(session.user)} email={session.user.email ?? ''} />
      </div>
    </header>
  )
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <ScrollToTop />
        <TopBar />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Login />} />
          <Route path="/about" element={<Lazy><About /></Lazy>} />
          <Route path="/contact" element={<Lazy><Contact /></Lazy>} />
          <Route path="/privacy" element={<Lazy><Privacy /></Lazy>} />
          <Route path="/terms" element={<Lazy><Terms /></Lazy>} />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/campaigns/:id"
            element={
              <ProtectedRoute>
                <CampaignDetail />
              </ProtectedRoute>
            }
          />
          <Route
            path="/campaigns/:id/metrics"
            element={
              <ProtectedRoute>
                <Metrics />
              </ProtectedRoute>
            }
          />
          <Route
            path="/tools"
            element={
              <ProtectedRoute>
                <Tools />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <Settings />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Lazy><NotFound /></Lazy>} />
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App
