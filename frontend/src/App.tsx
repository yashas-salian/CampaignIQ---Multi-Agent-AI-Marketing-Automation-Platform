import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { UI_LOCALES } from './i18n'
import { ThemeProvider, useTheme } from './lib/ThemeContext'
import { supabase } from './lib/supabaseClient'
import { useSession } from './lib/useAuth'
import CampaignDetail from './pages/CampaignDetail'
import Dashboard from './pages/Dashboard'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Metrics from './pages/Metrics'
import Settings from './pages/Settings'
import Tools from './pages/Tools'
import styles from './styles/shell.module.css'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  const { t } = useTranslation()
  if (loading) return <p className={`p-8 ${styles.muted}`}>{t('common.loading')}</p>
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

function ThemeToggle() {
  const { theme, toggleTheme } = useTheme()
  return (
    <button className={styles.themeToggle} aria-label="Toggle color theme" onClick={toggleTheme}>
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

function TopBar() {
  const { session } = useSession()
  const { t, i18n } = useTranslation()
  if (!session) return null
  return (
    <div className={styles.topbar}>
      <div className={styles.topbarInner}>
        <nav className={styles.topbarLinks}>
          <Link to="/dashboard" className={styles.topbarLink}>
            {t('common.dashboard')}
          </Link>
          <Link to="/tools" className={styles.topbarLink}>
            {t('common.tools')}
          </Link>
          <Link to="/settings" className={styles.topbarLink}>
            {t('common.settings')}
          </Link>
          <select
            value={i18n.language}
            onChange={(e) => i18n.changeLanguage(e.target.value)}
            className={`${styles.select} text-xs`}
          >
            {UI_LOCALES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </nav>
        <div className="flex items-center gap-3">
          <ThemeToggle />
          <button onClick={() => supabase.auth.signOut()} className={`text-sm ${styles.muted} hover:underline`}>
            {t('common.signOut', { email: session.user.email })}
          </button>
        </div>
      </div>
    </div>
  )
}

function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <TopBar />
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
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
        </Routes>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App
