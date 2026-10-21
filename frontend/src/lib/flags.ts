import { useEffect, useState } from 'react'

import { supabase } from './supabaseClient'

// Feature flags for the signed-in user, evaluated by the database function
// feature_enabled() -- the same rule the Python workers use, so a percentage
// rollout includes the same users on both sides. Unknown flags, signed-out
// visitors and errors all read as `fallback` (off by default).
const cache = new Map<string, Promise<boolean>>()

export function fetchFlag(key: string): Promise<boolean> {
  let pending = cache.get(key)
  if (!pending) {
    pending = Promise.resolve(supabase.rpc('feature_enabled', { flag_key: key }))
      .then(({ data, error }) => (error ? false : Boolean(data)))
      .catch(() => false)
    cache.set(key, pending)
  }
  return pending
}

/** Call on sign-in/sign-out: flags can differ per user. */
export function clearFlagCache() {
  cache.clear()
}

export function useFlag(key: string, fallback = false): boolean {
  const [enabled, setEnabled] = useState(fallback)
  useEffect(() => {
    let live = true
    fetchFlag(key).then((value) => live && setEnabled(value))
    return () => {
      live = false
    }
  }, [key])
  return enabled
}
