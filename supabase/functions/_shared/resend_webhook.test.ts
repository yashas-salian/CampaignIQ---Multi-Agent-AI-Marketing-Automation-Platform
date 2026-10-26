// Run: node --test supabase/functions/_shared/resend_webhook.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { createHmac } from 'node:crypto'
import { test } from 'node:test'

import { handleWebhook, verifySvix } from './resend_webhook.ts'

const rawSecret = Buffer.from('a-very-secret-signing-key-32byte!').toString('base64')
const SECRET = `whsec_${rawSecret}`
const NOW = 1_760_000_000
const sign = (id: string, ts: number, body: string, secret = rawSecret) =>
  'v1,' + createHmac('sha256', Buffer.from(secret, 'base64')).update(`${id}.${ts}.${body}`).digest('base64')

function request(body: object, opts: { id?: string; ts?: number; sig?: string; org?: string } = {}) {
  const raw = JSON.stringify(body)
  const id = opts.id ?? 'msg_1'
  const ts = opts.ts ?? NOW
  return new Request(`https://x.supabase.co/functions/v1/resend-webhook/${opts.org ?? '22222222-2222-2222-2222-222222222222'}`, {
    method: 'POST', body: raw,
    headers: { 'svix-id': id, 'svix-timestamp': String(ts), 'svix-signature': opts.sig ?? sign(id, ts, raw) },
  })
}

function deps(secret: string | null = SECRET) {
  const recorded: unknown[] = []
  return {
    recorded,
    d: {
      secret: async () => secret,
      record: async (e: unknown) => {
        recorded.push(e)
        return 'bounced'
      },
      now: () => NOW,
    },
  }
}

test('a correctly signed event verifies; a tampered one does not', async () => {
  const body = '{"type":"email.delivered"}'
  assert.equal(await verifySvix(body, { id: 'm', timestamp: String(NOW), signature: sign('m', NOW, body) }, SECRET, NOW), true)
  assert.equal(await verifySvix(body + ' ', { id: 'm', timestamp: String(NOW), signature: sign('m', NOW, body) }, SECRET, NOW), false)
})

test('any of several signatures may match (secret rotation)', async () => {
  const body = '{}'
  const sig = `v1,bm9wZQ== ${sign('m', NOW, body)}`
  assert.equal(await verifySvix(body, { id: 'm', timestamp: String(NOW), signature: sig }, SECRET, NOW), true)
})

test('an old timestamp is refused (replays)', async () => {
  const body = '{}'
  const old = NOW - 600
  assert.equal(await verifySvix(body, { id: 'm', timestamp: String(old), signature: sign('m', old, body) }, SECRET, NOW), false)
})

test('a bounce is recorded with its type, by the Resend email id', async () => {
  const { d, recorded } = deps()
  const res = await handleWebhook(request({ type: 'email.bounced', data: { email_id: 're_1', bounce: { type: 'Permanent', message: 'no such user' } } }), d)
  assert.equal(res.status, 200)
  assert.deepEqual(recorded, [{ org: '22222222-2222-2222-2222-222222222222', eventId: 'msg_1', type: 'email.bounced', emailId: 're_1', bounceType: 'Permanent' }])
})

test('a bad signature is refused and nothing is recorded', async () => {
  const { d, recorded } = deps()
  const res = await handleWebhook(request({ type: 'email.complained', data: { email_id: 're_1' } }, { sig: 'v1,AAAA' }), d)
  assert.equal(res.status, 401)
  assert.deepEqual(recorded, [])
})

test('an organisation without a stored secret is refused', async () => {
  const { d, recorded } = deps(null)
  const res = await handleWebhook(request({ type: 'email.delivered', data: { email_id: 're_1' } }), d)
  assert.equal(res.status, 404)
  assert.deepEqual(recorded, [])
})

test('a path that is not an organisation id is refused', async () => {
  const { d } = deps()
  const res = await handleWebhook(request({ type: 'email.delivered', data: { email_id: 're_1' } }, { org: 'nope' }), d)
  assert.equal(res.status, 400)
})
