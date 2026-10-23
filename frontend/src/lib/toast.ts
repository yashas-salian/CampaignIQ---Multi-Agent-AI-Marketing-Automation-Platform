/*
 * App-wide toasts. Call toast.success / toast.error / toast.info from anywhere
 * (components, providers, plain functions); components/Toaster renders them.
 * Field validation, page states and form outcomes stay inline; toasts are for
 * the result of an action or a background failure.
 */
export type ToastKind = 'success' | 'error' | 'info'
export interface ToastAction {
  label: string
  onClick: () => void
}
export interface ToastItem {
  id: number
  kind: ToastKind
  text: string
  action?: ToastAction
  bump: number // changes when an identical toast is raised again, restarting its timer
}

const MAX_VISIBLE = 3
export const DURATION: Record<ToastKind, number> = { success: 5000, info: 5000, error: 10000 }

let items: ToastItem[] = []
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

function push(kind: ToastKind, text: string, opts: { action?: ToastAction } = {}) {
  // The same message already on screen is refreshed, not stacked again.
  const same = items.find((t) => t.kind === kind && t.text === text)
  if (same) {
    items = items.map((t) => (t === same ? { ...t, action: opts.action ?? t.action, bump: t.bump + 1 } : t))
    emit()
    return same.id
  }
  const id = nextId++
  items = [...items, { id, kind, text, action: opts.action, bump: 0 }].slice(-MAX_VISIBLE)
  emit()
  return id
}

export const toast = {
  success: (text: string, opts?: { action?: ToastAction }) => push('success', text, opts),
  error: (text: string, opts?: { action?: ToastAction }) => push('error', text, opts),
  info: (text: string, opts?: { action?: ToastAction }) => push('info', text, opts),
  dismiss: (id: number) => {
    items = items.filter((t) => t.id !== id)
    emit()
  },
}

export const subscribeToasts = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
export const toastSnapshot = () => items
