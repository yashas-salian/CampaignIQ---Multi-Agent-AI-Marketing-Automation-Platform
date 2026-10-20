import type { ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { ThemeContext, type ThemeMode } from './useTheme'

const THEME_KEY = 'mos_theme'

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<ThemeMode>(null)

  useEffect(() => {
    let saved: string | null = null
    try {
      saved = localStorage.getItem(THEME_KEY)
    } catch {
      // ignore
    }
    if (saved === 'light' || saved === 'dark') setTheme(saved)
  }, [])

  useEffect(() => {
    const root = document.documentElement
    if (theme) root.setAttribute('data-theme', theme)
    else root.removeAttribute('data-theme')
  }, [theme])

  // With no saved choice, follow the OS preference (and its live changes) so
  // the toggle icon matches what's actually on screen.
  const [systemDark, setSystemDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false)
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)')
    if (!mq) return
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  const resolved = theme ?? (systemDark ? 'dark' : 'light')

  const toggleTheme = useCallback(() => {
    const current = document.documentElement.getAttribute('data-theme')
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches
    const effectiveDark = current ? current === 'dark' : prefersDark
    const next: ThemeMode = effectiveDark ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem(THEME_KEY, next)
    } catch {
      // ignore
    }
  }, [])

  return <ThemeContext.Provider value={{ theme: resolved, toggleTheme }}>{children}</ThemeContext.Provider>
}
