import { createClient } from '@supabase/supabase-js'

// The anon key is safe to expose in the browser bundle: it carries no
// privilege by itself, RLS policies (scoped to auth.uid()) are what actually
// restrict which rows a signed-in user's requests can touch.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error('Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY in frontend/.env')
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
