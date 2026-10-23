import { useEffect } from 'react'

/*
 * Page-level loading: while anything is registered, components/PageLoader
 * covers the page with a blurred overlay so a half-loaded page never shows.
 * Pages register with usePageLoading(isStillLoading); route and auth waits
 * use <LoadingMarker /> from components/PageLoader.
 */
const active = new Set<symbol>()
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())

/** Register one loading task; call the returned function when it's done. */
export function startLoading(): () => void {
  const key = Symbol('loading')
  active.add(key)
  emit()
  return () => {
    if (active.delete(key)) emit()
  }
}

/** A load failed: drop the overlay so its error toast (with Retry) can be seen. */
export function clearLoading() {
  if (!active.size) return
  active.clear()
  emit()
}

export const subscribeLoading = (l: () => void) => {
  listeners.add(l)
  return () => {
    listeners.delete(l)
  }
}
export const isLoading = () => active.size > 0

/** Show the page loader while `on` is true. */
export function usePageLoading(on: boolean) {
  useEffect(() => (on ? startLoading() : undefined), [on])
}
