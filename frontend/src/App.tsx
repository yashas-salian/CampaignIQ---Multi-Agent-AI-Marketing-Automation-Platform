import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Toaster from './components/Toaster'
import AppSidebar from './components/AppSidebar'
import NotificationBell from './components/NotificationBell'
import { APP_PREFIXES, setDrawerOpen } from './lib/shell'
import PageLoader, { LoadingMarker } from './components/PageLoader'
import { signOutWithToast } from './lib/notify'
import { UI_LOCALES } from './i18n'
import LogoMark from './components/LogoMark'
import Select from './components/Select'
import OrgProvider from './lib/OrgProvider'
import { NEXT_KEY } from './lib/site'
import { useOrg } from './lib/useOrg'
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
const Calendar = lazy(() => import('./pages/Calendar'))
const Admin = lazy(() => import('./pages/Admin'))
const Metrics = lazy(() => import('./pages/Metrics'))
const Settings = lazy(() => import('./pages/Settings'))
const Tools = lazy(() => import('./pages/Tools'))
const ToolsHistory = lazy(() => import('./pages/ToolsHistory'))
const ModelCard = lazy(() => import('./pages/ModelCard'))
const Playbooks = lazy(() => import('./pages/Playbooks'))
const Competitors = lazy(() => import('./pages/Competitors'))
const BrandMemory = lazy(() => import('./pages/BrandMemory'))
const Contacts = lazy(() => import('./pages/Contacts'))
const Unsubscribe = lazy(() => import('./pages/Unsubscribe'))
const Join = lazy(() => import('./pages/Join'))
const Confirm = lazy(() => import('./pages/Confirm'))
// Secondary public pages, also on demand.
const About = lazy(() => import('./pages/About'))
const Contact = lazy(() => import('./pages/Contact'))
const Privacy = lazy(() => import('./pages/Privacy'))
const Terms = lazy(() => import('./pages/Terms'))
const NotFound = lazy(() => import('./pages/NotFound'))
const Docs = lazy(() => import('./pages/Docs'))
const Status = lazy(() => import('./pages/Status'))
const AcceptInvite = lazy(() => import('./pages/AcceptInvite'))


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
  return <Suspense fallback={<LoadingMarker />}>{children}</Suspense>
}

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  const fallback = <LoadingMarker />
  const { pathname, search } = useLocation()
  if (loading) return fallback
  if (!session) {
    try {
      sessionStorage.setItem(NEXT_KEY, pathname + search)
    } catch {
      // storage blocked: the user lands on the dashboard instead
    }
    return <Navigate to="/login" replace />
  }
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


/**
 * Username cell with a dropdown (account email, Settings, Sign out). Opens on
 * hover, on keyboard focus, and on tap for touch screens; Esc or an outside
 * click closes it.
 */
function AccountMenu({ name, email }: { name: string | null; email: string }) {
  const { t, i18n } = useTranslation()
  const { orgs, active, setActive } = useOrg()
  const [isAdmin, setIsAdmin] = useState(false)
  useEffect(() => {
    supabase.rpc('is_platform_admin').then(({ data }) => setIsAdmin(Boolean(data)))
  }, [])
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
        {orgs.length > 1 && (
          <div className={styles.menuOrgs} role="group" aria-label={t('org.switch')}>
            {orgs.map((o) => (
              <button
                key={o.id}
                role="menuitemradio"
                aria-checked={o.id === active?.id}
                type="button"
                className={`${styles.menuItem} ${o.id === active?.id ? styles.menuItemActive : ''}`}
                onClick={() => {
                  setActive(o.id)
                  setOpen(false)
                }}
              >
                {o.personal ? t('org.personal') : o.name}
              </button>
            ))}
          </div>
        )}
        {/* Phones only (CSS): the language picker moves here from the top bar. */}
        <label className={styles.menuLang}>
          <span>Language</span>
          <Select
            variant="tile"
            aria-label="Language"
            value={i18n.language}
            onChange={(v) => i18n.changeLanguage(v)}
            options={UI_LOCALES.map((l) => ({ value: l.code, label: l.label }))}
          />
        </label>
        <Link role="menuitem" to="/settings#account" className={styles.menuItem} onClick={() => setOpen(false)}>
          {t('common.settings')}
        </Link>
        <Link role="menuitem" to="/settings#team" className={styles.menuItem} onClick={() => setOpen(false)}>
          {t('org.team')}
        </Link>
        {isAdmin && (
          <Link role="menuitem" to="/admin" className={styles.menuItem} onClick={() => setOpen(false)}>
            {t('admin.title')}
          </Link>
        )}
        <button role="menuitem" type="button" className={`${styles.menuItem} ${styles.menuDanger}`} onClick={() => signOutWithToast(t)}>
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
      {/* Phones: opens the sidebar drawer (desktop has the always-there rail). */}
      <button type="button" className={`${styles.topbarCell} ${styles.menuButton}`} onClick={() => setDrawerOpen(true)} aria-label={t('nav.menu')}>
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
      <Link to="/dashboard" className={`${styles.topbarCell} ${styles.topbarBrand}`}>
        <LogoMark className={styles.topbarLogo} />
        CampaignIQ
      </Link>
      <div className={`${styles.topbarLinks} ${styles.topbarRight}`}>
        <label className={`${styles.topbarCell} ${styles.topbarLang}`}>
          <span className="sr-only">Language</span>
          <Select
            variant="tile"
            aria-label="Language"
            value={i18n.language}
            onChange={(v) => i18n.changeLanguage(v)}
            options={UI_LOCALES.map((l) => ({ value: l.code, label: l.label }))}
          />
        </label>
        <NotificationBell />
        <ThemeToggle />
        <AccountMenu name={displayName(session.user)} email={session.user.email ?? ''} />
      </div>
    </header>
  )
}

/** The sidebar, on signed-in app pages only (same rule as the top bar). */
function AppChrome() {
  const { session } = useSession()
  const { pathname } = useLocation()
  if (!session || !APP_PREFIXES.some((p) => pathname.startsWith(p))) return null
  return <AppSidebar />
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <ScrollToTop />
        <OrgProvider>
        <TopBar />
        <AppChrome />
        <div id="app-main">
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Login />} />
          <Route path="/about" element={<Lazy><About /></Lazy>} />
          <Route path="/contact" element={<Lazy><Contact /></Lazy>} />
          <Route path="/privacy" element={<Lazy><Privacy /></Lazy>} />
          <Route path="/terms" element={<Lazy><Terms /></Lazy>} />
          <Route path="/docs" element={<Lazy><Docs /></Lazy>} />
          <Route path="/status" element={<Lazy><Status /></Lazy>} />
          <Route path="/unsubscribe" element={<Lazy><Unsubscribe /></Lazy>} />
          <Route path="/join/:slug" element={<Lazy><Join /></Lazy>} />
          <Route path="/confirm" element={<Lazy><Confirm /></Lazy>} />
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
            path="/admin"
            element={
              <ProtectedRoute>
                <Admin />
              </ProtectedRoute>
            }
          />
          <Route
            path="/calendar"
            element={
              <ProtectedRoute>
                <Calendar />
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
            path="/tools/history"
            element={
              <ProtectedRoute>
                <ToolsHistory />
              </ProtectedRoute>
            }
          />
          <Route
            path="/competitors"
            element={
              <ProtectedRoute>
                <Competitors />
              </ProtectedRoute>
            }
          />
          <Route
            path="/contacts"
            element={
              <ProtectedRoute>
                <Contacts />
              </ProtectedRoute>
            }
          />
          <Route
            path="/memory"
            element={
              <ProtectedRoute>
                <BrandMemory />
              </ProtectedRoute>
            }
          />
          <Route
            path="/playbooks"
            element={
              <ProtectedRoute>
                <Playbooks />
              </ProtectedRoute>
            }
          />
          <Route
            path="/models"
            element={
              <ProtectedRoute>
                <ModelCard />
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
          <Route
            path="/invite/:token"
            element={
              <ProtectedRoute>
                <AcceptInvite />
              </ProtectedRoute>
            }
          />
          <Route path="*" element={<Lazy><NotFound /></Lazy>} />
        </Routes>
        </div>
        <PageLoader />
        <Toaster />
        </OrgProvider>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App
