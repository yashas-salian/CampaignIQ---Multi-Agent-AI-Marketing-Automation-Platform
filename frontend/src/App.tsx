import type { ReactNode } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { supabase } from './lib/supabaseClient'
import { useSession } from './lib/useAuth'
import CampaignDetail from './pages/CampaignDetail'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Settings from './pages/Settings'
import Tools from './pages/Tools'

function ProtectedRoute({ children }: { children: ReactNode }) {
  const { session, loading } = useSession()
  if (loading) return <p className="p-8 text-gray-500">Loading…</p>
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

function TopBar() {
  const { session } = useSession()
  if (!session) return null
  return (
    <div className="max-w-3xl mx-auto px-8 pt-4 flex justify-between items-center">
      <nav className="flex gap-4 text-sm">
        <Link to="/" className="text-gray-500 hover:underline">
          Dashboard
        </Link>
        <Link to="/tools" className="text-gray-500 hover:underline">
          Tools
        </Link>
        <Link to="/settings" className="text-gray-500 hover:underline">
          Settings
        </Link>
      </nav>
      <button onClick={() => supabase.auth.signOut()} className="text-sm text-gray-500 hover:underline">
        Sign out ({session.user.email})
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
