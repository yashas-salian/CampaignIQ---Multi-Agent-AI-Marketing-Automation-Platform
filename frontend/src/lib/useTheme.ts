import { createContext, useContext } from 'react'

export type ThemeMode = 'light' | 'dark' | null

export interface ThemeContextValue {
  // The theme actually in effect: the saved choice, else the OS preference.
  theme: 'light' | 'dark'
  toggleTheme: () => void
}

// Lives outside ThemeContext.tsx so that file exports only a component,
// which keeps Vite fast refresh working for it.
export const ThemeContext = createContext<ThemeContextValue | null>(null)

export function useTheme() {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
