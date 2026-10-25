import type { TFunction } from 'i18next'

import { clearLoading } from './loading'
import { toast } from './toast'
import { supabase } from './supabaseClient'

/** The message inside a Supabase / fetch / thrown error, whatever its shape. */
export function messageOf(error: unknown): string {
  if (!error) return ''
  if (typeof error === 'string') return error
  if (typeof error === 'object' && 'message' in error) return String((error as { message: unknown }).message)
  return String(error)
}

/** "Failed: <reason>" as an error toast. Returns true when there was an error. */
export function toastFailure(t: TFunction, error: unknown): boolean {
  if (!error) return false
  toast.error(t('st.failed', { message: messageOf(error) }))
  return true
}

/**
 * A background load failed: one de-duplicated error toast with a Retry
 * button, instead of silently showing empty data.
 */
export function toastLoadError(t: TFunction, error: unknown, retry: () => void): boolean {
  if (!error) return false
  clearLoading()
  if (isNotSetUp(error)) {
    // The server doesn't have this feature's tables yet (its migration isn't applied): retrying can't help.
    toast.error(t('toast.notSetUp'))
    return true
  }
  toast.error(t('toast.loadFailed'), { action: { label: t('toast.retry'), onClick: retry } })
  return true
}

/** PostgREST's "table not found" (PGRST205) or Postgres's "relation does not exist" (42P01). */
export function isNotSetUp(error: unknown): boolean {
  const code = typeof error === 'object' && error && 'code' in error ? String((error as { code: unknown }).code) : ''
  return code === 'PGRST205' || code === '42P01'
}

/** Sign out, saying so if it fails (otherwise the session would silently stay). */
export async function signOutWithToast(t: TFunction) {
  const { error } = await supabase.auth.signOut()
  toastFailure(t, error)
}

/** Copy text and confirm it; clipboard can be blocked, which is said too. */
export async function copyWithToast(t: TFunction, text: string) {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(t('toast.copied'))
  } catch {
    toast.error(t('toast.copyFailed'))
  }
}
