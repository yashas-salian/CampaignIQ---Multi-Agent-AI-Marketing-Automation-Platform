// The unsubscribe link and one-click List-Unsubscribe header of every campaign
// email. Public (no JWT: people unsubscribing aren't users); the random
// per-person token is the only key, and an unknown token reveals nothing.
// Request handling: ../_shared/unsubscribe.ts. APP_BASE_URL is the website.
import { createClient } from 'jsr:@supabase/supabase-js@2'

import { CORS_HEADERS, handleUnsubscribe } from '../_shared/unsubscribe.ts'

const db = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)

Deno.serve(async (req) => {
  try {
    return await handleUnsubscribe(req, {
      async info(token) {
        const { data, error } = await db.rpc('unsubscribe_info', { p_token: token })
        if (error) throw error
        return data
      },
      async unsubscribe(token) {
        const { data, error } = await db.rpc('unsubscribe_by_token', { p_token: token })
        if (error) throw error
        return data
      },
      async erase(token) {
        const { data, error } = await db.rpc('erase_by_token', { p_token: token })
        if (error) throw error
        return data
      },
    }, Deno.env.get('APP_BASE_URL') ?? 'http://localhost:5173')
  } catch (err) {
    console.error('unsubscribe failed:', err instanceof Error ? err.message : err)
    return new Response('something went wrong, please try again', { status: 500, headers: CORS_HEADERS })
  }
})
