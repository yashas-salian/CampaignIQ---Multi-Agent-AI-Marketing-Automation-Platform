import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useState } from 'react'

const THEME_KEY = 'mos_theme'

type ThemeMode = 'light' | 'dark' | null

interface ThemeContextValue {
  theme: ThemeMode
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

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

  return <ThemeContext.Provider value={{ theme, toggleTheme }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
