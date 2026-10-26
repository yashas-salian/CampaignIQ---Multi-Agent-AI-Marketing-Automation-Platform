// The public unsubscribe endpoint behind every campaign email (the
// unsubscribe Edge Function). Database calls are injected so the request
// handling runs under Node for tests (supabase/functions/_shared/unsubscribe.test.ts).
//
//   GET  ?t=<token>                          -> 302 to the website's unsubscribe page (never unsubscribes:
//                                               mail scanners open links)
//   POST ?t=<token>  List-Unsubscribe=One-Click -> unsubscribe now, 200 with an empty body (RFC 8058)
//   POST {t, action: "info" | "unsubscribe" | "erase"} -> JSON for the website page ("erase": also delete my details)

export interface UnsubscribeInfo {
  brand: string
  slug: string
  status: string
  language: string | null
  privacy_url: string | null
}

export interface UnsubscribeDb {
  info(token: string): Promise<UnsubscribeInfo | null>
  unsubscribe(token: string): Promise<{ status: string; brand: string } | null>
  erase(token: string): Promise<{ status: string; brand: string } | null>
}

const TOKEN = /^[0-9a-f]{32}$/

export const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...CORS_HEADERS } })

export async function handleUnsubscribe(req: Request, db: UnsubscribeDb, appUrl: string): Promise<Response> {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS_HEADERS })
  const url = new URL(req.url)
  const type = req.headers.get('Content-Type') ?? ''
  let body: Record<string, unknown> = {}
  let oneClick = false
  if (req.method === 'POST') {
    const raw = await req.text()
    if (type.includes('application/json')) body = JSON.parse(raw || '{}')
    else oneClick = new URLSearchParams(raw).get('List-Unsubscribe') === 'One-Click'
  }
  const token = String(body.t ?? url.searchParams.get('t') ?? '')
  if (!TOKEN.test(token)) return new Response('bad token', { status: 400, headers: CORS_HEADERS })

  if (req.method === 'GET') {
    return new Response(null, { status: 302, headers: { Location: `${appUrl.replace(/\/$/, '')}/unsubscribe?t=${token}` } })
  }
  if (oneClick) {
    await db.unsubscribe(token)
    return new Response('', { status: 200, headers: CORS_HEADERS })
  }
  if (body.action === 'info') {
    const info = await db.info(token)
    return info ? json(info) : json({ error: 'not found' }, 404)
  }
  if (body.action === 'erase') {
    await db.unsubscribe(token) // the suppression is recorded as an unsubscribe first, whatever happens next
    const done = await db.erase(token)
    return done ? json(done) : json({ error: 'not found' }, 404)
  }
  if (body.action === 'unsubscribe') {
    const done = await db.unsubscribe(token)
    return done ? json(done) : json({ error: 'not found' }, 404)
  }
  return json({ error: 'unknown action' }, 400)
}
