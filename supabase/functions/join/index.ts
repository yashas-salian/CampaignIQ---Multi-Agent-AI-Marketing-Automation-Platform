// A brand's public sign-up form (/join/{slug} on the website) and its
// double opt-in: no JWT (the people signing up aren't users). Confirmation
// emails go through the brand's own Resend account, with its sending-only key
// read from Vault by the service role. Handling: ../_shared/signup.ts.
import { createClient } from 'jsr:@supabase/supabase-js@2'

import { CORS_HEADERS, handleJoin } from '../_shared/signup.ts'

const db = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)

async function rpc<T>(name: string, args: Record<string, unknown>): Promise<T> {
  const { data, error } = await db.rpc(name, args)
  if (error) throw error
  return data as T
}

async function config(org: string) {
  return await rpc<Record<string, string | null> | null>('email_sending_config', { p_org: org })
}

Deno.serve(async (req) => {
  try {
    return await handleJoin(req, {
      info: (slug) => rpc('signup_info', { p_slug: slug }),
      signup: (a) => rpc('signup_contact', {
        p_slug: a.slug, p_email: a.email, p_first_name: a.firstName, p_language: a.language, p_campaign: a.campaign,
        p_consent_text: a.consentText, p_ip: a.ip,
      }),
      confirm: (token) => rpc('confirm_contact', { p_token: token }),
      resubscribe: (t) => rpc('resubscribe_by_token', { p_token: t }),
      async sender(org) {
        const c = await config(org)
        return c ? { brand: c.brand_name!, postalAddress: c.postal_address ?? '', mode: c.mode as 'live' | 'sandbox', sandboxTo: c.sandbox_to } : null
      },
      async send(org, to, subject, html) {
        const c = await config(org)
        if (!c) throw new Error('email is not connected')
        const res = await fetch('https://api.resend.com/emails', {
          method: 'POST',
          headers: { Authorization: `Bearer ${c.api_key}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ from: c.from, to: [to], subject, html, ...(c.reply_to ? { reply_to: c.reply_to } : {}) }),
        })
        if (!res.ok) throw new Error(`Resend ${res.status}: ${(await res.text()).slice(0, 200)}`)
      },
      recordSystemEmail: (org) => rpc('record_system_email', { p_org: org, p_kind: 'confirmation' }),
    }, Deno.env.get('APP_BASE_URL') ?? 'http://localhost:5173')
  } catch (err) {
    console.error('join failed:', err instanceof Error ? err.message : err)
    return new Response(JSON.stringify({ status: 'try_later' }), { status: 500, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } })
  }
})
