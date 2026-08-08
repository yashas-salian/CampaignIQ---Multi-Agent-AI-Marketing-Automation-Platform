import { createClient } from '@supabase/supabase-js'

// M3: single-tenant, no auth/RLS yet, so the anon key with RLS-off tables is
// safe to ship in the browser bundle (there is nothing per-user to leak).
// M4 turns RLS on and adds real login — do not carry this pattern forward
// past M3 once tenant-owned data exists.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in frontend/.env')
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
