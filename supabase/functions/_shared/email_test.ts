// "Send me a test" at Gate 2 (the email-test Edge Function): one copy of the
// round's email, through the organisation's own Resend account, to the
// signed-in person's own address (or, in sandbox mode, the account owner's).
// Never to a contact. Runs under Node for tests (supabase/functions/_shared/email_test.test.ts).

export interface TestCampaign { id: string; org_id: string; idea: string; copy_text: string | null; brand: string; postal_address: string | null }
export interface SendingConfig { mode: string; api_key: string; from: string; sandbox_to: string | null }

export interface EmailTestDeps {
  user(): Promise<{ id: string; email: string } | null>
  campaign(id: string): Promise<TestCampaign | null>
  canTest(org: string): Promise<boolean>
  config(org: string): Promise<SendingConfig | null>
  send(config: SendingConfig, to: string, subject: string, html: string): Promise<void>
  count(org: string): Promise<void>
}

export const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } })
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export async function handleEmailTest(req: Request, d: EmailTestDeps): Promise<Response> {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS_HEADERS })
  const me = await d.user()
  if (!me) return json({ error: 'sign in first' }, 401)
  const body = await req.json().catch(() => ({})) as { campaign_id?: string }
  const campaign = body.campaign_id ? await d.campaign(String(body.campaign_id)) : null
  if (!campaign) return json({ error: 'campaign not found' }, 404)
  if (!(await d.canTest(campaign.org_id))) return json({ error: 'only approvers, owners, admins and marketers can send a test' }, 403)
  const config = await d.config(campaign.org_id)
  if (!config) return json({ error: 'connect a Resend account first', code: 'not_connected' }, 409)
  if (!campaign.copy_text) return json({ error: 'this round has no copy yet', code: 'no_copy' }, 409)

  const to = config.mode === 'sandbox' && config.sandbox_to ? config.sandbox_to : me.email
  const html = `<p>${esc(campaign.copy_text).replace(/\n/g, '<br>')}</p>`
    + '<hr style="border:0;border-top:1px solid #e5e5e5;margin:24px 0 12px">'
    + `<p style="font-size:12px;color:#666">A test of this round's campaign email. The real emails also greet each person by name and `
    + `carry their own unsubscribe link.<br>${esc(campaign.brand)} · ${esc(campaign.postal_address ?? '')}</p>`
  await d.send(config, to, `[Test] ${campaign.idea.slice(0, 70)}`, html)
  await d.count(campaign.org_id)
  return json({ sent_to: to })
}
