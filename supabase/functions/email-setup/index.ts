// Settings → Email sending: connect an organisation's own Resend account.
// JWT verification ON (supabase/config.toml), and only the organisation's
// owners and admins may use it.
//
//   POST {action: "inspect", org_id, api_key}  -> {domains, existing_webhooks}
//   POST {action: "connect", org_id, api_key, mode: "live" | "sandbox",
//         domain_id?, from_local?, from_name, reply_to?, sandbox_to?}  -> {masked_key, mode, from_email}
//
// The full-access key in the request is used for these calls only and never
// stored or logged; save_email_connection() (service role) keeps the
// sending-only key and the webhook secret in Supabase Vault.
import { createClient } from 'jsr:@supabase/supabase-js@2'

import { connectAccount, inspectAccount, SetupError } from '../_shared/resend_setup.ts'

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

async function handle(req: Request): Promise<Response> {
  const auth = req.headers.get('Authorization')
  if (!auth) return json({ error: 'missing Authorization header' }, 401)
  const url = Deno.env.get('SUPABASE_URL')!
  const user = createClient(url, Deno.env.get('SUPABASE_ANON_KEY')!, { global: { headers: { Authorization: auth } } })
  const { data: who, error: whoError } = await user.auth.getUser()
  if (whoError || !who.user) return json({ error: 'invalid session' }, 401)

  const body = await req.json().catch(() => ({}))
  const orgId = String(body.org_id ?? '')
  const apiKey = String(body.api_key ?? '').trim()
  if (!orgId || apiKey.length < 8) return json({ error: 'org_id and api_key are required' }, 400)
  const { data: canManage } = await user.rpc('org_can', { p_org: orgId, p_permission: 'manage' })
  if (!canManage) return json({ error: 'only owners and admins can connect email sending' }, 403)

  try {
    if (body.action === 'inspect') {
      const out = await inspectAccount(apiKey)
      return json({ domains: out.domains, existing_webhooks: out.existingWebhooks })
    }
    if (body.action !== 'connect') return json({ error: 'action must be inspect or connect' }, 400)

    const mode = body.mode === 'live' ? 'live' : 'sandbox'
    const fromName = String(body.from_name ?? '').trim().slice(0, 80)
    if (!fromName) return json({ error: 'from_name is required', code: 'bad_from' }, 400)
    const { data: status } = await user.rpc('email_status', { p_org: orgId })
    if (!status?.postal_address) {
      return json({ error: 'add your postal address to the brand kit first: every marketing email must show it', code: 'postal_address_missing' }, 400)
    }
    const publicUrl = Deno.env.get('PUBLIC_FUNCTIONS_URL') ?? `${url}/functions/v1`
    const conn = await connectAccount({
      key: apiKey, mode, domainId: body.domain_id, fromLocal: String(body.from_local ?? ''),
      sandboxTo: body.sandbox_to, webhookUrl: `${publicUrl}/resend-webhook/${orgId}`,
    })
    const service = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)
    const { data: masked, error } = await service.rpc('save_email_connection', {
      p_org: orgId, p_mode: mode, p_sending_key: conn.sendingKey, p_from_email: conn.fromEmail, p_from_name: fromName,
      p_reply_to: body.reply_to || null, p_domain: conn.domain, p_domain_id: conn.domainId,
      p_sandbox_to: mode === 'sandbox' ? String(body.sandbox_to ?? '') : null,
      p_webhook_id: conn.webhookId, p_webhook_secret: conn.webhookSecret,
    })
    if (error) return json({ error: error.message }, 500)
    return json({ masked_key: masked, mode, from_email: conn.fromEmail })
  } catch (err) {
    if (err instanceof SetupError) return json({ error: err.message, code: err.code }, 400)
    throw err
  }
}

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS_HEADERS })
  let res: Response
  try {
    res = await handle(req)
  } catch (err) {
    res = json({ error: `internal error: ${err instanceof Error ? err.message : String(err)}` }, 500)
  }
  const headers = new Headers(res.headers)
  for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v)
  return new Response(res.body, { status: res.status, headers })
})
