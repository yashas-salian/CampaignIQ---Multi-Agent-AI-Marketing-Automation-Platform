import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import { useAuthTargets } from '../lib/site'
import LogoMark from './LogoMark'
import { useTheme } from '../lib/useTheme'
import styles from './public.module.css'


export const ArrowIcon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// Section links point at the Landing page; Landing scrolls to the hash.
const LINKS: { to: string; label: string; page?: boolean }[] = [
  { to: '/#loop', label: 'The loop' },
  { to: '/#pricing', label: 'Pricing' },
  { to: '/docs', label: 'Docs', page: true },
  { to: '/about', label: 'About', page: true },
  { to: '/contact', label: 'Contact', page: true },
]

/** Segmented tile navbar shared by every public page. Hides on scroll down. */
export default function PublicNav() {
  const { theme, toggleTheme } = useTheme()
  const { authed, loginTo, signupTo } = useAuthTargets()
  const [hidden, setHidden] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const barRef = useRef<HTMLDivElement>(null)
  const { pathname, hash } = useLocation()

  // The phone menu closes on navigation, Esc, or a tap outside the bar.
  useEffect(() => setMenuOpen(false), [pathname, hash])
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: PointerEvent) => {
      if (!barRef.current?.contains(e.target as Node)) setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  useEffect(() => {
    let lastY = window.scrollY
    let ticking = false
    function onScroll() {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        const y = window.scrollY
        setHidden(y > lastY && y > 160)
        lastY = y
        ticking = false
      })
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <header className={`${styles.nav} ${hidden && !menuOpen ? styles.navHidden : ''}`}>
      <div className={styles.navBar} ref={barRef}>
        {/* Named even on phones, where the wordmark is hidden. */}
        <Link to="/" className={`${styles.navCell} ${styles.navBrand}`} aria-label="CampaignIQ">

          <span className={styles.logo}>
            <LogoMark />
            <span className={styles.brandText}>CampaignIQ</span>
          </span>
        </Link>
        <nav className={styles.navLinks}>
          {LINKS.map((l) =>
            l.page ? (
              <NavLink key={l.to} to={l.to} className={({ isActive }) => `${styles.navCell} wipe-host ${isActive ? styles.navActive : ''}`}>
                <span className="link-wipe">{l.label}</span>
              </NavLink>
            ) : (
              <Link key={l.to} to={l.to} className={`${styles.navCell} wipe-host`}>
                <span className="link-wipe">{l.label}</span>
              </Link>
            ),
          )}
        </nav>
        <div className={styles.navRight}>
          <button className={`${styles.navCell} ${styles.themeToggle}`} aria-label="Toggle color theme" onClick={toggleTheme}>
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
          {/* Only what this visitor can use now: signed out, log in or sign up; signed in, their dashboard. */}
          {authed ? (
            <Link className={`${styles.navCell} ${styles.navCta}`} to="/dashboard">
              Dashboard
              <ArrowIcon className={styles.arrow} />
            </Link>
          ) : (
            <>
              <Link className={`${styles.navCell} ${styles.navLogin} wipe-host`} to={loginTo}>
                <span className="link-wipe">Log in</span>
              </Link>
              <Link className={`${styles.navCell} ${styles.navCta}`} to={signupTo}>
                Get started
                <ArrowIcon className={styles.arrow} />
              </Link>
            </>
          )}
          {/* Phones/tablets: the section links live behind this button. */}
          <button
            type="button"
            className={`${styles.navCell} ${styles.menuBtn}`}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            aria-expanded={menuOpen}
            aria-controls="public-menu"
            onClick={() => setMenuOpen((o) => !o)}
          >
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              {menuOpen ? (
                <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              ) : (
                <path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
        <nav id="public-menu" className={`${styles.mobileMenu} ${menuOpen ? styles.mobileMenuOpen : ''}`} aria-label="Site">
          {LINKS.map((l) => (
            <Link key={l.to} to={l.to} className={`${styles.mobileItem} wipe-host`}>
              <span className="link-wipe">{l.label}</span>
            </Link>
          ))}
          <Link to={authed ? '/dashboard' : loginTo} className={`${styles.mobileItem} wipe-host`}>
            <span className="link-wipe">{authed ? 'Dashboard' : 'Log in'}</span>
          </Link>
        </nav>
      </div>
    </header>
  )
}
