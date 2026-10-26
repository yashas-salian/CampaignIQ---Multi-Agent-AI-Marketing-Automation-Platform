// Resend's delivery events for one organisation (the resend-webhook Edge
// Function, at /resend-webhook/{org_id}). Resend signs webhooks with Svix:
//   svix-signature: "v1,<base64 HMAC-SHA256(secret, `${svix-id}.${svix-timestamp}.${body}`)>" (space-separated list)
//   secret: "whsec_<base64 key>", per organisation (stored in Vault when it connected).
// Runs under Node for tests (supabase/functions/_shared/resend_webhook.test.ts).

const encoder = new TextEncoder()
const TOLERANCE_SECONDS = 300
const ORG = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

function fromBase64(s: string): Uint8Array<ArrayBuffer> {
  const bin = atob(s)
  const out = new Uint8Array(new ArrayBuffer(bin.length))
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function toBase64(bytes: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(bytes)))
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

export async function verifySvix(
  body: string, headers: { id: string | null; timestamp: string | null; signature: string | null }, secret: string, now: number,
): Promise<boolean> {
  if (!headers.id || !headers.timestamp || !headers.signature) return false
  const ts = Number(headers.timestamp)
  if (!Number.isFinite(ts) || Math.abs(now - ts) > TOLERANCE_SECONDS) return false
  const key = await crypto.subtle.importKey('raw', fromBase64(secret.replace(/^whsec_/, '')), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  const expected = toBase64(await crypto.subtle.sign('HMAC', key, encoder.encode(`${headers.id}.${headers.timestamp}.${body}`)))
  return headers.signature.split(' ').some((part) => {
    const [version, sig] = part.split(',')
    return version === 'v1' && !!sig && safeEqual(sig, expected)
  })
}

export interface EmailEvent { org: string; eventId: string; type: string; emailId: string; bounceType: string | null }

export interface WebhookDeps {
  secret(org: string): Promise<string | null>
  record(event: EmailEvent): Promise<string>
  now?: () => number
}

const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

export async function handleWebhook(req: Request, deps: WebhookDeps): Promise<Response> {
  if (req.method !== 'POST') return reply({ error: 'POST only' }, 405)
  const org = new URL(req.url).pathname.split('/').filter(Boolean).pop() ?? ''
  if (!ORG.test(org)) return reply({ error: 'unknown organisation' }, 400)
  const body = await req.text()
  const secret = await deps.secret(org)
  if (!secret) return reply({ error: 'unknown organisation' }, 404)
  const headers = { id: req.headers.get('svix-id'), timestamp: req.headers.get('svix-timestamp'), signature: req.headers.get('svix-signature') }
  const now = deps.now ? deps.now() : Math.floor(Date.now() / 1000)
  if (!(await verifySvix(body, headers, secret, now))) return reply({ error: 'bad signature' }, 401)

  const event = JSON.parse(body) as { type?: string; data?: { email_id?: string; bounce?: { type?: string } } }
  if (!event.type || !event.data?.email_id) return reply({ ok: true, outcome: 'nothing to record' })
  const outcome = await deps.record({
    org, eventId: headers.id!, type: event.type, emailId: event.data.email_id, bounceType: event.data.bounce?.type ?? null,
  })
  return reply({ ok: true, outcome })
}
