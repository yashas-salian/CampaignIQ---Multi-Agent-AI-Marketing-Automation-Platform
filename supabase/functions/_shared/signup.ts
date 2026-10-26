// A brand's public sign-up form with double opt-in (the join Edge Function).
// Database and sending are injected so the request handling runs under Node
// for tests (supabase/functions/_shared/signup.test.ts).
//
//   POST {action: "info", slug}                              -> the brand's public name and look
//   POST {action: "signup", slug, email, first_name?, language?, c?, consent_text, company (honeypot)}
//                                                            -> {status: "check_inbox" | "closed"}; 429 when rate-limited
//   POST {action: "confirm", token}                          -> {status: "subscribed", brand}
//   POST {action: "resubscribe", t}                          -> a fresh confirmation (from an unsubscribe link)
//
// The answer to a sign-up never says whether the address is already on the
// list (no fishing for who's a customer): subscribed, blocked and new all read
// "check your inbox".

export interface SignupInfo { brand: string; slug: string; privacy_url: string | null; brand_color: string | null; logo_path: string | null; open: boolean }
export interface SignupResult { action: string; token?: string; email?: string; org_id?: string; first_name?: string | null; language?: string | null }
export interface Sender { brand: string; postalAddress: string; mode: 'live' | 'sandbox'; sandboxTo: string | null }

export interface JoinDeps {
  info(slug: string): Promise<SignupInfo | null>
  signup(args: { slug: string; email: string; firstName: string | null; language: string | null; campaign: string | null;
    consentText: string; ip: string }): Promise<SignupResult>
  confirm(token: string): Promise<{ status: string; brand: string } | null>
  resubscribe(unsubToken: string): Promise<SignupResult | null>
  sender(org: string): Promise<Sender | null>
  send(org: string, to: string, subject: string, html: string): Promise<void>
  recordSystemEmail(org: string): Promise<void>
}

export const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } })

const TOKEN = /^[0-9a-f]{32}$/
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

const WORDS: Record<string, { subject: string; hi: string; hiAnon: string; body: string; button: string; ignore: string }> = {
  en: { subject: 'Confirm your subscription to {brand}', hi: 'Hi {name},', hiAnon: 'Hi,', body: 'Please confirm you want marketing emails from {brand}.',
    button: 'Confirm my subscription', ignore: "If you didn't sign up, ignore this email: nothing happens without a click." },
  es: { subject: 'Confirma tu suscripción a {brand}', hi: 'Hola, {name}:', hiAnon: 'Hola:', body: 'Confirma que quieres recibir emails de marketing de {brand}.',
    button: 'Confirmar mi suscripción', ignore: 'Si no te registraste, ignora este email: no pasa nada sin un clic.' },
  fr: { subject: 'Confirmez votre abonnement à {brand}', hi: 'Bonjour {name},', hiAnon: 'Bonjour,', body: 'Confirmez que vous souhaitez recevoir les emails marketing de {brand}.',
    button: 'Confirmer mon abonnement', ignore: "Si vous ne vous êtes pas inscrit, ignorez cet email : rien ne se passe sans un clic." },
  hi: { subject: '{brand} की सदस्यता की पुष्टि करें', hi: 'नमस्ते {name},', hiAnon: 'नमस्ते,', body: 'कृपया पुष्टि करें कि आप {brand} से मार्केटिंग ईमेल पाना चाहते हैं।',
    button: 'मेरी सदस्यता की पुष्टि करें', ignore: 'अगर आपने साइन अप नहीं किया, तो यह ईमेल अनदेखा करें: क्लिक के बिना कुछ नहीं होता।' },
  pt: { subject: 'Confirme sua inscrição na {brand}', hi: 'Olá, {name},', hiAnon: 'Olá,', body: 'Confirme que você quer receber emails de marketing da {brand}.',
    button: 'Confirmar minha inscrição', ignore: 'Se você não se cadastrou, ignore este email: nada acontece sem um clique.' },
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

export function confirmationEmail(a: { brand: string; firstName: string | null; language: string | null; link: string; postalAddress: string }) {
  const w = WORDS[(a.language ?? 'en').slice(0, 2)] ?? WORDS.en
  const brand = esc(a.brand)
  const hi = a.firstName?.trim() ? w.hi.replace('{name}', esc(a.firstName.trim())) : w.hiAnon
  const html = `<p>${hi}</p><p>${w.body.replace('{brand}', brand)}</p>`
    + `<p><a href="${esc(a.link)}" style="display:inline-block;padding:12px 20px;border-radius:999px;background:#111;color:#fff;text-decoration:none">${w.button}</a></p>`
    + `<p style="font-size:12px;color:#666">${esc(w.ignore)}<br>${brand} · ${esc(a.postalAddress)}</p>`
  return { subject: w.subject.replace('{brand}', a.brand), html }
}

async function sendConfirmation(r: SignupResult, d: JoinDeps, appUrl: string): Promise<Response> {
  const sender = await d.sender(r.org_id!)
  if (!sender) return json({ status: 'closed' })
  const { subject, html } = confirmationEmail({ brand: sender.brand, firstName: r.first_name ?? null, language: r.language ?? 'en',
    link: `${appUrl.replace(/\/$/, '')}/confirm?token=${r.token}`, postalAddress: sender.postalAddress })
  const sandbox = sender.mode === 'sandbox'
  try {
    await d.send(r.org_id!, sandbox ? sender.sandboxTo! : r.email!, sandbox ? `[Sandbox: for ${r.email}] ${subject}` : subject, html)
  } catch (err) {
    console.warn('confirmation email failed:', err instanceof Error ? err.message : err)
    return json({ status: 'try_later' }, 503)
  }
  await d.recordSystemEmail(r.org_id!)
  return json({ status: 'check_inbox' })
}

export async function handleJoin(req: Request, d: JoinDeps, appUrl: string): Promise<Response> {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS_HEADERS })
  if (req.method !== 'POST') return json({ error: 'POST only' }, 405)
  const body = await req.json().catch(() => ({})) as Record<string, unknown>

  if (body.action === 'info') {
    const info = await d.info(String(body.slug ?? ''))
    return info ? json(info) : json({ error: 'not found' }, 404)
  }
  if (body.action === 'signup') {
    if (body.company) return json({ status: 'check_inbox' }) // the hidden field: a bot
    const email = String(body.email ?? '').trim()
    const consentText = String(body.consent_text ?? '').trim()
    if (!email || !consentText || consentText.length > 1000) return json({ error: 'email and consent wording are required' }, 400)
    const ip = (req.headers.get('x-forwarded-for') ?? '').split(',')[0].trim() || 'unknown'
    const r = await d.signup({
      slug: String(body.slug ?? ''), email, firstName: body.first_name ? String(body.first_name).slice(0, 80) : null,
      language: body.language ? String(body.language).slice(0, 2) : null, campaign: UUID.test(String(body.c ?? '')) ? String(body.c) : null,
      consentText, ip,
    })
    if (r.action === 'confirm_email') return sendConfirmation(r, d, appUrl)
    if (r.action === 'rate_limited') return json({ status: 'rate_limited' }, 429)
    if (r.action === 'invalid') return json({ status: 'invalid' }, 400)
    if (r.action === 'already' || r.action === 'blocked') return json({ status: 'check_inbox' })
    return json({ status: 'closed' })
  }
  if (body.action === 'confirm') {
    const token = String(body.token ?? '')
    const done = TOKEN.test(token) ? await d.confirm(token) : null
    return done ? json(done) : json({ error: 'not found' }, 404)
  }
  if (body.action === 'resubscribe') {
    const t = String(body.t ?? '')
    const r = TOKEN.test(t) ? await d.resubscribe(t) : null
    if (!r) return json({ error: 'not found' }, 404)
    if (r.action === 'confirm_email') return sendConfirmation(r, d, appUrl)
    return json({ status: r.action === 'already' ? 'subscribed' : 'closed' })
  }
  return json({ error: 'unknown action' }, 400)
}
