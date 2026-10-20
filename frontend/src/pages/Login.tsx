import type { FormEvent } from 'react'
import { useEffect, useState } from 'react'
import { Trans, useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import Photo from '../components/Photo'
import { PHOTOS } from '../lib/photos'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import { useTheme } from '../lib/useTheme'
import styles from './Login.module.css'

// Supabase reports a failed email link or OAuth sign-in by redirecting with
// error=...&error_code=...&error_description=... in the URL: in the #hash for
// the implicit flow, in the ?query for PKCE. Check both.
function authLinkError(t: TFunction): string | null {
  for (const raw of [window.location.hash.slice(1), window.location.search.slice(1)]) {
    const params = new URLSearchParams(raw)
    if (!params.get('error')) continue
    if (params.get('error_code') === 'otp_expired') return t('login.linkExpired')
    return params.get('error_description') ?? params.get('error')
  }
  return null
}

type OAuthProvider = 'google' | 'github'

const GoogleIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
    <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
    <path fill="#FBBC05" d="M5.84 14.09A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.09V7.07H2.18A11 11 0 0 0 1 12c0 1.77.43 3.45 1.18 4.93l3.66-2.84z" />
    <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1A11 11 0 0 0 2.18 7.07l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
  </svg>
)

const GitHubIcon = () => (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <path
      fill="currentColor"
      d="M12 .5a11.5 11.5 0 0 0-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.52-1.33-1.28-1.69-1.28-1.69-1.05-.71.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 0 1 5.77 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.8 1.19 1.83 1.19 3.09 0 4.42-2.69 5.39-5.26 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0 0 12 .5z"
    />
  </svg>
)

const LogoMark = () => (
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    <path d="M12 3v5l4-2.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export default function Login() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { session, loading: sessionLoading } = useSession()
  const { theme, toggleTheme } = useTheme()
  const mode: 'signin' | 'signup' = location.pathname === '/signup' ? 'signup' : 'signin'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(() => authLinkError(t))
  // A notice can arrive from a sign-up that switched us over to /login.
  const [notice, setNotice] = useState<string | null>(() => (location.state as { notice?: string } | null)?.notice ?? null)
  const [loading, setLoading] = useState(false)

  // Already signed in: there's nothing to do here.
  useEffect(() => {
    if (!sessionLoading && session) navigate('/dashboard', { replace: true })
  }, [sessionLoading, session, navigate])

  // The error now lives in state; drop it from the URL so a refresh doesn't repeat it.
  useEffect(() => {
    if (window.location.hash.includes('error=') || window.location.search.includes('error=')) {
      window.history.replaceState(window.history.state, '', window.location.pathname)
    }
  }, [])

  const [oauthLoading, setOauthLoading] = useState<OAuthProvider | null>(null)

  // Hands off to Google/GitHub; the browser comes back to /login, where the
  // session effect above forwards a signed-in user to /dashboard and
  // authLinkError() shows any failure.
  async function handleOAuth(provider: OAuthProvider) {
    setError(null)
    setNotice(null)
    setOauthLoading(provider)
    const { error: oauthError } = await supabase.auth.signInWithOAuth({
      provider,
      options: { redirectTo: `${window.location.origin}/login` },
    })
    if (oauthError) {
      setError(oauthError.message)
      setOauthLoading(null)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setNotice(null)

    const { data, error: authError } =
      mode === 'signin'
        ? await supabase.auth.signInWithPassword({ email, password })
        : await supabase.auth.signUp({ email, password })

    setLoading(false)
    if (authError) {
      setError(authError.message)
      return
    }
    // With email confirmation on, signUp succeeds but returns no session until
    // the link is clicked, so /dashboard would just bounce back here.
    if (!data.session) {
      navigate('/login', { replace: true, state: { notice: t('login.checkEmail', { email }) } })
      setNotice(t('login.checkEmail', { email }))
      setPassword('')
      return
    }
    navigate('/dashboard')
  }

  return (
    <div className={styles.page}>
      <div className={styles.formSide}>
        <header className={styles.top}>
          <Link to="/" className={styles.logo}>
            <LogoMark />
            MarketingOS
          </Link>
          <div className={styles.topRight}>
            <Link to="/" className={`${styles.back} link-wipe`}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {t('login.backHome')}
            </Link>
            <button className={styles.themeToggle} aria-label="Toggle color theme" onClick={toggleTheme}>
              {theme === 'light' ? (
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.4 5.4 0 0 1 12 3z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
        </header>

        <main className={styles.formWrap}>
          <div className={styles.card}>
            <div className={styles.tabs} role="tablist" data-mode={mode}>
              <span className={styles.tabIndicator} aria-hidden="true" />
              <Link role="tab" aria-selected={mode === 'signin'} to="/login" replace className={mode === 'signin' ? styles.tabActive : ''}>
                {t('login.titleSignin')}
              </Link>
              <Link role="tab" aria-selected={mode === 'signup'} to="/signup" replace className={mode === 'signup' ? styles.tabActive : ''}>
                {t('login.titleSignup')}
              </Link>
            </div>

            {/* Keyed by mode so the heading re-plays its entrance when switching tabs. */}
            <div className={styles.heading} key={mode}>
              <h1 className={styles.title}>{mode === 'signin' ? t('login.titleSignin') : t('login.titleSignup')}</h1>
              <p className={styles.subtitle}>{mode === 'signin' ? t('login.subtitleSignin') : t('login.subtitleSignup')}</p>
            </div>

            <div className={styles.oauth}>
              {(
                [
                  ['google', <GoogleIcon key="g" />, t('login.continueGoogle')],
                  ['github', <GitHubIcon key="gh" />, t('login.continueGithub')],
                ] as const
              ).map(([provider, icon, label]) => (
                <button
                  key={provider}
                  type="button"
                  className={styles.oauthBtn}
                  disabled={oauthLoading !== null || loading}
                  onClick={() => handleOAuth(provider)}
                >
                  {oauthLoading === provider ? <span className={styles.spinnerDark} aria-hidden="true" /> : icon}
                  {label}
                </button>
              ))}
            </div>

            <div className={styles.divider}>
              <span>{t('login.or')}</span>
            </div>

            <form onSubmit={handleSubmit} className={styles.form}>
              <label className={styles.field}>
                <span>{t('login.emailLabel')}</span>
                <input
                  type="email"
                  required
                  autoComplete="email"
                  placeholder={t('login.emailPlaceholder')}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </label>
              <label className={styles.field}>
                <span>{t('login.passwordLabel')}</span>
                <div className={styles.passwordRow}>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    required
                    minLength={6}
                    autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                    placeholder={t('login.passwordPlaceholder')}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className={styles.eye}
                    aria-label={showPassword ? t('login.hidePassword') : t('login.showPassword')}
                    onClick={() => setShowPassword((s) => !s)}
                  >
                    {showPassword ? (
                      <svg viewBox="0 0 24 24" fill="none">
                        <path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10.4 10.4 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.2 4.1M6.6 6.6C3.9 8.4 2.5 12 2.5 12S6 19 12 19c1.6 0 3-.4 4.3-1" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" fill="none">
                        <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" stroke="currentColor" strokeWidth="1.8" />
                        <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
                      </svg>
                    )}
                  </button>
                </div>
                {mode === 'signup' && <small className={styles.hint}>{t('login.passwordHint')}</small>}
              </label>

              {error && (
                <p className={`${styles.alert} ${styles.alertError}`} role="alert">
                  {error}
                </p>
              )}
              {notice && (
                <p className={`${styles.alert} ${styles.alertNotice}`} role="status">
                  {notice}
                </p>
              )}

              <button type="submit" disabled={loading} className={styles.submit}>
                {loading ? <span className={styles.spinner} aria-hidden="true" /> : null}
                {mode === 'signin' ? t('login.submitSignin') : t('login.submitSignup')}
                {!loading && (
                  <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </form>

            <p className={styles.switch}>
              <Link className="link-wipe" to={mode === 'signin' ? '/signup' : '/login'} replace>
                {mode === 'signin' ? t('login.toggleToSignup') : t('login.toggleToSignin')}
              </Link>
            </p>

            <p className={styles.legal}>
              <Trans
                i18nKey="login.agree"
                components={{
                  terms: <Link className="link-wipe" to="/terms" />,
                  privacy: <Link className="link-wipe" to="/privacy" />,
                }}
              />
            </p>
          </div>
        </main>

      </div>

      <aside className={styles.visualSide} aria-hidden="true">
        <div className={styles.glow} />
        <div className={styles.visualInner}>
          <h2>{t('login.panelTitle')}</h2>
          <p>{t('login.panelBody')}</p>
          <div className={styles.mediaFrame}>
            <div className={styles.media}>
              <Photo photo={PHOTOS.workspace} sizes="(max-width: 960px) 0px, 560px" />
            </div>
            <div className={`${styles.chip} ${styles.chipA}`}>
              <span className={styles.chipKicker}>{t('login.chipFeasibility')}</span>
              <strong>78</strong>/100
            </div>
            <div className={`${styles.chip} ${styles.chipB}`}>
              {t('login.chipGate')}
            </div>
          </div>
        </div>
      </aside>
    </div>
  )
}
