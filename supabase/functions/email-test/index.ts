// "Send me a test" at Gate 2: the round's email, once, to the signed-in
// person (JWT verification ON). The campaign is read with the caller's own
// session, so RLS decides whether they may see it; only the sending key is
// read with the service role. Handling: ../_shared/email_test.ts.
import { createClient } from 'jsr:@supabase/supabase-js@2'

import { CORS_HEADERS, handleEmailTest } from '../_shared/email_test.ts'

const url = Deno.env.get('SUPABASE_URL')!
const service = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS_HEADERS })
  const user = createClient(url, Deno.env.get('SUPABASE_ANON_KEY')!, {
    global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } },
  })
  try {
    return await handleEmailTest(req, {
      async user() {
        const { data } = await user.auth.getUser()
        return data.user?.email ? { id: data.user.id, email: data.user.email } : null
      },
      async campaign(id) {
        const { data: c } = await user.from('campaigns').select('id,org_id,idea,current_round').eq('id', id).maybeSingle()
        if (!c) return null
        const [{ data: round }, { data: org }, { data: kit }] = await Promise.all([
          user.from('iterations').select('copy_text').eq('campaign_id', id).eq('round_number', c.current_round)
            .order('preflight_attempt', { ascending: false }).limit(1).maybeSingle(),
          user.from('organizations').select('name').eq('id', c.org_id).maybeSingle(),
          user.from('brand_kits').select('postal_address').eq('org_id', c.org_id).maybeSingle(),
        ])
        return { id: c.id, org_id: c.org_id, idea: c.idea, copy_text: round?.copy_text ?? null, brand: org?.name ?? '',
          postal_address: kit?.postal_address ?? null }
      },
      async canTest(org) {
        const [approve, create] = await Promise.all([
          user.rpc('org_can', { p_org: org, p_permission: 'approve' }), user.rpc('org_can', { p_org: org, p_permission: 'create' }),
        ])
        return !!approve.data || !!create.data
      },
      async config(org) {
        const { data } = await service.rpc('email_sending_config', { p_org: org })
        return data
      },
      async send(config, to, subject, html) {
        const res = await fetch('https://api.resend.com/emails', {
          method: 'POST',
          headers: { Authorization: `Bearer ${config.api_key}`, 'Content-Type': 'application/json' },
          body: JSON.stringify({ from: config.from, to: [to], subject, html }),
        })
        if (!res.ok) throw new Error(`Resend ${res.status}: ${(await res.text()).slice(0, 200)}`)
      },
      async count(org) {
        await service.rpc('record_system_email', { p_org: org, p_kind: 'test' })
      },
    })
  } catch (err) {
    return new Response(JSON.stringify({ error: err instanceof Error ? err.message : String(err) }), {
      status: 502, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS },
    })
  }
})
