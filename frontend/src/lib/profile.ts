import type { User } from '@supabase/supabase-js'
import { supabase } from './supabaseClient'

/*
 * The username lives in the user's own Supabase Auth profile
 * (user_metadata.username): no table or migration, the same place for every
 * sign-in method, and updating it refreshes the session everywhere. It's a
 * display name only. user_metadata is user-editable by design, so never use
 * it for authorization.
 */

// Letters in any script (incl. combining marks, e.g. Hindi), numbers, spaces, . _ -
const USERNAME_RE = /^[\p{L}\p{M}\p{N} ._-]{2,32}$/u

export const normalizeUsername = (raw: string) => raw.trim().replace(/\s+/g, ' ')

export const isValidUsername = (raw: string) => USERNAME_RE.test(normalizeUsername(raw))

/** The user's chosen username, or null if they haven't set one. */
export function usernameOf(user: User | null | undefined): string | null {
  const value = user?.user_metadata?.username
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/**
 * Name to greet the user by: their username, else the name Google/GitHub
 * supplied at sign-in. Never derived from the email address.
 */
export function displayName(user: User | null | undefined): string | null {
  const meta = user?.user_metadata ?? {}
  for (const value of [meta.username, meta.full_name, meta.name]) {
    if (typeof value === 'string' && value.trim()) return value.trim()
  }
  return null
}

/** Saves the username to the signed-in user's profile. */
export async function saveUsername(raw: string) {
  return supabase.auth.updateUser({ data: { username: normalizeUsername(raw) } })
}
