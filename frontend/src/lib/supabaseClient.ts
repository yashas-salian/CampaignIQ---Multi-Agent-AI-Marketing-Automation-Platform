import { createClient } from '@supabase/supabase-js'

// The anon key is safe to expose in the browser bundle: it carries no
// privilege by itself, RLS policies (scoped to auth.uid()) are what actually
// restrict which rows a signed-in user's requests can touch.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in frontend/.env')
}

// Supabase Auth and the data API run on different servers whose clocks can be
// a few seconds apart, so a token used right after sign-in can be rejected as
// "JWT issued at future" (PGRST303). That clears up within seconds, so retry
// that one error briefly instead of showing an empty page. Everything else,
// including real auth failures, passes straight through.
const CLOCK_SKEW_RETRIES = [1000, 2500]

async function skewTolerantFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let res = await fetch(input, init)
  for (const delay of CLOCK_SKEW_RETRIES) {
    if (res.status !== 401) return res
    const body = await res.clone().text()
    if (!body.includes('PGRST303')) return res
    await new Promise((resolve) => setTimeout(resolve, delay))
    res = await fetch(input, init)
  }
  return res
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  global: { fetch: skewTolerantFetch },
})
