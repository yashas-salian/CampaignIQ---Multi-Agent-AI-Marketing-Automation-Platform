import type { FormEvent } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/shell.module.css'

export default function Login() {
  const { t } = useTranslation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)

    const { error: authError } =
      mode === 'signin'
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password })

    setLoading(false)
    if (authError) {
      setError(authError.message)
      return
    }
    navigate('/dashboard')
  }

  return (
    <div className={`max-w-sm mx-auto p-8 ${styles.shell}`}>
      <h1 className="text-2xl mb-6">{mode === 'signin' ? t('login.titleSignin') : t('login.titleSignup')}</h1>
      <form onSubmit={handleSubmit} className="space-y-3">
        <input
          type="email"
          required
          placeholder={t('login.emailPlaceholder')}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={styles.input}
        />
        <input
          type="password"
          required
          placeholder={t('login.passwordPlaceholder')}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={styles.input}
        />
        {error && <p className="text-sm" style={{ color: 'var(--mos-danger)' }}>{error}</p>}
        <button type="submit" disabled={loading} className={`w-full ${styles.btn} ${styles.btnPrimary}`}>
          {mode === 'signin' ? t('login.submitSignin') : t('login.submitSignup')}
        </button>
      </form>
      <button
        onClick={() => setMode(mode === 'signin' ? 'signup' : 'signin')}
        className={`text-sm ${styles.muted} hover:underline mt-4`}
      >
        {mode === 'signin' ? t('login.toggleToSignup') : t('login.toggleToSignin')}
      </button>
    </div>
  )
}
