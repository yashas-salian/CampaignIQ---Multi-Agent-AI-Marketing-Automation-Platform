import { useSyncExternalStore } from 'react'

/*
 * Shared state for the app shell (components/AppSidebar):
 *  - whether the sidebar drawer is open on phones (the top bar's menu button);
 *  - the Settings page's sections and the one in view, which the sidebar lists
 *    under "Settings" (the page publishes them; the sidebar reads them).
 */
export interface SettingsNav {
  sections: { id: string; label: string }[]
  current: string
  pick: (id: string) => void
}
interface Shell {
  drawerOpen: boolean
  settings: SettingsNav | null
}

// The app bar and sidebar belong to the logged-in app only; public pages (and
// the 404) render their own header even for a logged-in visitor.
// Logged-in pages: they get the top bar and the sidebar (public pages have their own navbar
// and never the sidebar). Every <ProtectedRoute> in App.tsx must start with one of these:
// e2e/app.spec.ts checks it.
export const APP_PREFIXES = [
  '/dashboard', '/calendar', '/campaigns', '/tools', '/settings', '/admin', '/models', '/playbooks', '/competitors', '/memory', '/contacts', '/invite',
]

let state: Shell = { drawerOpen: false, settings: null }
const listeners = new Set<() => void>()
const set = (patch: Partial<Shell>) => {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
const snapshot = () => state

export const useShell = () => useSyncExternalStore(subscribe, snapshot, snapshot)
export const setDrawerOpen = (drawerOpen: boolean) => set({ drawerOpen })
export const setSettingsNav = (settings: SettingsNav | null) => set({ settings })
