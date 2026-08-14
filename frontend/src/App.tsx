import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { UI_LOCALES } from './i18n'
import { supabase } from './lib/supabaseClient'
import { useSession } from './lib/useAuth'
import CampaignDetail from './pages/CampaignDetail'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Metrics from './pages/Metrics'
import Settings from './pages/Settings'
import Tools from './pages/Tools'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  const { t } = useTranslation()
  if (loading) return <p className="p-8 text-gray-500">{t('common.loading')}</p>
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

function TopBar() {
  const { session } = useSession()
  const { t, i18n } = useTranslation()
  if (!session) return null
  return (
    <div className="max-w-3xl mx-auto px-8 pt-4 flex justify-between items-center">
      <nav className="flex gap-4 text-sm items-center">
        <Link to="/" className="text-gray-500 hover:underline">
          {t('common.dashboard')}
        </Link>
        <Link to="/tools" className="text-gray-500 hover:underline">
          {t('common.tools')}
        </Link>
        <Link to="/settings" className="text-gray-500 hover:underline">
          {t('common.settings')}
        </Link>
        <select
          value={i18n.language}
          onChange={(e) => i18n.changeLanguage(e.target.value)}
          className="text-xs border rounded-lg px-1 py-0.5"
        >
          {UI_LOCALES.map((l) => (
            <option key={l.code} value={l.code}>
              {l.label}
            </option>
          ))}
        </select>
      </nav>
      <button onClick={() => supabase.auth.signOut()} className="text-sm text-gray-500 hover:underline">
        {t('common.signOut', { email: session.user.email })}
      </button>
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <TopBar />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          path="/"
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
  )
}

export default App
