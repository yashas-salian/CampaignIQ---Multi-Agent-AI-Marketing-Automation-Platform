// Run: node --test supabase/functions/_shared/resend_setup.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { connectAccount, inspectAccount, SetupError } from './resend_setup.ts'

type Call = { method: string; path: string; body?: Record<string, unknown>; auth: string }

/** A fake Resend API: answers by method + path, records every call. */
function fakeResend(over: Record<string, (body?: Record<string, unknown>) => [number, unknown]> = {}) {
  const calls: Call[] = []
  const routes: Record<string, (body?: Record<string, unknown>) => [number, unknown]> = {
    'GET /domains': () => [200, { data: [{ id: 'dom_1', name: 'brewline.coffee', status: 'verified' }, { id: 'dom_2', name: 'new.coffee', status: 'pending' }] }],
    'GET /webhooks': () => [200, { data: [] }],
    'POST /webhooks': () => [201, { object: 'webhook', id: 'wh_1', signing_secret: 'whsec_123' }],
    'POST /api-keys': () => [201, { id: 'key_1', token: 're_sendonly_9876' }],
    'POST /emails': () => [200, { id: 'em_1' }],
    'DELETE /webhooks/wh_1': () => [200, {}],
    'DELETE /api-keys/key_1': () => [200, {}],
    ...over,
  }
  const fetchFn = async (url: string | URL, init?: RequestInit) => {
    const u = new URL(String(url))
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, path: u.pathname, body, auth: String((init?.headers as Record<string, string>)?.Authorization ?? '') })
    const route = routes[`${method} ${u.pathname}`]
    const [status, payload] = route ? route(body) : [404, { message: 'not found' }]
    return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
  }
  return { calls, fetchFn: fetchFn as typeof fetch }
}

const HOOK = 'https://x.supabase.co/functions/v1/resend-webhook/org-1'

test('inspecting a key lists its domains, verified first, and whether a webhook slot looks free', async () => {
  const { fetchFn, calls } = fakeResend()
  const out = await inspectAccount('re_full_1234', fetchFn)
  assert.deepEqual(out.domains.map((d) => [d.name, d.verified]), [['brewline.coffee', true], ['new.coffee', false]])
  assert.equal(out.existingWebhooks, 0)
  assert.ok(calls.every((c) => c.auth === 'Bearer re_full_1234'))
})

test('a key Resend refuses is reported as such, not as a crash', async () => {
  const { fetchFn } = fakeResend({ 'GET /domains': () => [401, { message: 'API key is invalid' }] })
  await assert.rejects(inspectAccount('re_bad', fetchFn), (e: unknown) => e instanceof SetupError && e.code === 'invalid_key')
})

test('a sending-only key is told apart: it cannot set anything up', async () => {
  const { fetchFn } = fakeResend({ 'GET /domains': () => [403, { message: 'restricted_api_key', name: 'restricted_api_key' }] })
  await assert.rejects(inspectAccount('re_send', fetchFn), (e: unknown) => e instanceof SetupError && e.code === 'needs_full_access')
})

test('connecting live: webhook installed, a sending-only key made for that one domain, and the full key never kept', async () => {
  const { fetchFn, calls } = fakeResend()
  const out = await connectAccount({ key: 're_full_1234', mode: 'live', domainId: 'dom_1', fromLocal: 'Hello', webhookUrl: HOOK }, fetchFn)
  assert.deepEqual(out, { sendingKey: 're_sendonly_9876', webhookId: 'wh_1', webhookSecret: 'whsec_123',
    fromEmail: 'hello@brewline.coffee', domain: 'brewline.coffee', domainId: 'dom_1' })
  const hook = calls.find((c) => c.method === 'POST' && c.path === '/webhooks')!
  assert.equal(hook.body!.endpoint, HOOK)
  assert.deepEqual(hook.body!.events, ['email.delivered', 'email.bounced', 'email.complained', 'email.delivery_delayed'])
  const key = calls.find((c) => c.path === '/api-keys')!
  assert.deepEqual(key.body, { name: 'CampaignIQ sending', permission: 'sending_access', domain_id: 'dom_1' })
  assert.ok(!JSON.stringify(out).includes('re_full_1234'))
})

test('a domain that is not verified is refused before anything is created', async () => {
  const { fetchFn, calls } = fakeResend()
  await assert.rejects(connectAccount({ key: 'k', mode: 'live', domainId: 'dom_2', fromLocal: 'hi', webhookUrl: HOOK }, fetchFn),
    (e: unknown) => e instanceof SetupError && e.code === 'domain_not_verified')
  assert.ok(!calls.some((c) => c.method === 'POST'))
})

test('a from address that is not a plain mailbox name is refused', async () => {
  const { fetchFn } = fakeResend()
  await assert.rejects(connectAccount({ key: 'k', mode: 'live', domainId: 'dom_1', fromLocal: 'a@b', webhookUrl: HOOK }, fetchFn),
    (e: unknown) => e instanceof SetupError && e.code === 'bad_from')
})

test('when the webhook slot is taken, setup stops and creates no key', async () => {
  const { fetchFn, calls } = fakeResend({
    'GET /webhooks': () => [200, { data: [{ id: 'wh_theirs' }] }],
    'POST /webhooks': () => [422, { message: 'You have reached the maximum number of webhooks for your plan' }],
  })
  await assert.rejects(connectAccount({ key: 'k', mode: 'live', domainId: 'dom_1', fromLocal: 'hi', webhookUrl: HOOK }, fetchFn),
    (e: unknown) => e instanceof SetupError && e.code === 'webhook_slot_taken')
  assert.ok(!calls.some((c) => c.path === '/api-keys'))
  assert.ok(!calls.some((c) => c.method === 'DELETE' && c.path === '/webhooks/wh_theirs')) // never touches the brand's webhook
})

test('sandbox: the owner address is proven with one test send, from the sandbox sender', async () => {
  const { fetchFn, calls } = fakeResend()
  const out = await connectAccount({ key: 'k', mode: 'sandbox', sandboxTo: 'ava@example.com', fromLocal: '', webhookUrl: HOOK }, fetchFn)
  assert.equal(out.fromEmail, 'onboarding@resend.dev')
  const key = calls.find((c) => c.path === '/api-keys')!
  assert.deepEqual(key.body, { name: 'CampaignIQ sending', permission: 'sending_access' }) // the sandbox domain can't be targeted
  const send = calls.find((c) => c.path === '/emails')!
  assert.equal(send.auth, 'Bearer re_sendonly_9876')
  assert.deepEqual(send.body!.to, ['ava@example.com'])
  assert.equal(send.body!.from, 'CampaignIQ <onboarding@resend.dev>')
})

test('sandbox with the wrong owner address: refused, and what was created is removed again', async () => {
  const { fetchFn, calls } = fakeResend({
    'POST /emails': () => [403, { message: 'You can only send testing emails to your own email address (owner@x.io).' }],
  })
  await assert.rejects(connectAccount({ key: 'k', mode: 'sandbox', sandboxTo: 'someone@else.io', fromLocal: '', webhookUrl: HOOK }, fetchFn),
    (e: unknown) => e instanceof SetupError && e.code === 'sandbox_address')
  assert.ok(calls.some((c) => c.method === 'DELETE' && c.path === '/webhooks/wh_1'))
  assert.ok(calls.some((c) => c.method === 'DELETE' && c.path === '/api-keys/key_1'))
})
