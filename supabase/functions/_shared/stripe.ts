// Minimal Stripe helpers for Deno Edge Functions (no SDK): form-encoded REST
// calls and webhook signature verification. Also runs under Node 24 for tests
// (supabase/functions/_shared/stripe.test.ts).

const encoder = new TextEncoder()

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

async function hmacSha256(secret: string, payload: string): Promise<string> {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return hex(await crypto.subtle.sign('HMAC', key, encoder.encode(payload)))
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i)
  return diff === 0
}

/**
 * Verify a `Stripe-Signature` header (`t=<unix>,v1=<hex>[,v1=...]`) against the
 * raw body: v1 = HMAC-SHA256(secret, `${t}.${body}`), and t within the tolerance.
 */
export async function verifyStripeSignature(
  body: string,
  header: string | null,
  secret: string,
  { toleranceSeconds = 300, now = Date.now() / 1000 } = {},
): Promise<boolean> {
  if (!header || !secret) return false
  const parts = header.split(',').map((p) => p.trim().split('='))
  const timestamp = Number(parts.find(([k]) => k === 't')?.[1])
  const signatures = parts.filter(([k]) => k === 'v1').map(([, v]) => v)
  if (!Number.isFinite(timestamp) || !signatures.length) return false
  if (Math.abs(now - timestamp) > toleranceSeconds) return false
  const expected = await hmacSha256(secret, `${timestamp}.${body}`)
  return signatures.some((s) => safeEqual(s, expected))
}

/** Flatten {a: {b: 1}, c: [x]} into Stripe's form encoding (a[b]=1&c[0]=x). */
export function formEncode(data: Record<string, unknown>, prefix = ''): string {
  const pairs: string[] = []
  for (const [key, value] of Object.entries(data)) {
    if (value === undefined || value === null) continue
    const name = prefix ? `${prefix}[${key}]` : key
    if (Array.isArray(value)) {
      value.forEach((v, i) => {
        if (typeof v === 'object' && v !== null) pairs.push(formEncode(v as Record<string, unknown>, `${name}[${i}]`))
        else pairs.push(`${encodeURIComponent(`${name}[${i}]`)}=${encodeURIComponent(String(v))}`)
      })
    } else if (typeof value === 'object') {
      pairs.push(formEncode(value as Record<string, unknown>, name))
    } else {
      pairs.push(`${encodeURIComponent(name)}=${encodeURIComponent(String(value))}`)
    }
  }
  return pairs.filter(Boolean).join('&')
}

export async function stripe(path: string, secretKey: string, params?: Record<string, unknown>, method = 'POST') {
  const res = await fetch(`https://api.stripe.com/v1/${path}`, {
    method,
    headers: { Authorization: `Bearer ${secretKey}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params && method !== 'GET' ? formEncode(params) : undefined,
  })
  const json = await res.json()
  if (!res.ok) throw new Error(json?.error?.message ?? `Stripe ${res.status}`)
  return json
}
