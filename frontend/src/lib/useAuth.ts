import type { Session } from '@supabase/supabase-js'
import { useEffect, useState } from 'react'
import { clearFlagCache } from './flags'
import { supabase } from './supabaseClient'

export function useSession() {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })
    const { data: listener } = supabase.auth.onAuthStateChange((event, newSession) => {
      // Flags are per user: re-evaluate after a sign-in or sign-out.
      if (event === 'SIGNED_IN' || event === 'SIGNED_OUT') clearFlagCache()
      setSession(newSession)
    })
    return () => listener.subscription.unsubscribe()
  }, [])

  return { session, loading }
}
