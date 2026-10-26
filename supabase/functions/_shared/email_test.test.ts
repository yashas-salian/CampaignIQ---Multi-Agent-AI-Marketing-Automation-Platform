// Run: node --test supabase/functions/_shared/email_test.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { handleEmailTest, type EmailTestDeps } from './email_test.ts'

const CAMPAIGN = { id: '33333333-3333-3333-3333-333333333333', org_id: 'o1', idea: 'Order-ahead coffee',
  copy_text: 'Skip the queue: <your> coffee is ready.\nSee you soon.', brand: 'Brewline', postal_address: '12 Bean St' }

function deps(over: Partial<EmailTestDeps> = {}) {
  const sent: { to: string; subject: string; html: string; from: string }[] = []
  const counted: string[] = []
  const d: EmailTestDeps = {
    user: async () => ({ id: 'u1', email: 'ava@example.com' }),
    campaign: async (id) => (id === CAMPAIGN.id ? CAMPAIGN : null),
    canTest: async () => true,
    config: async () => ({ mode: 'live', api_key: 're_send', from: 'Brewline <hello@brewline.coffee>', sandbox_to: null }),
    send: async (config, to, subject, html) => { sent.push({ to, subject, html, from: config.from }) },
    count: async (org) => { counted.push(org) },
    ...over,
  }
  return { d, sent, counted }
}

const post = (body: object) => new Request('https://x/functions/v1/email-test', { method: 'POST', body: JSON.stringify(body) })

test('a test of the round\'s email goes to the signed-in person only, labelled, from the brand', async () => {
  const { d, sent, counted } = deps()
  const res = await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), d)
  assert.deepEqual(await res.json(), { sent_to: 'ava@example.com' })
  assert.equal(sent.length, 1)
  assert.equal(sent[0].to, 'ava@example.com')
  assert.equal(sent[0].from, 'Brewline <hello@brewline.coffee>')
  assert.equal(sent[0].subject, '[Test] Order-ahead coffee')
  assert.ok(sent[0].html.includes('Skip the queue: &lt;your&gt; coffee is ready.<br>See you soon.'))
  assert.ok(sent[0].html.includes('12 Bean St'))
  assert.deepEqual(counted, ['o1'])
})

test('in sandbox mode the test goes to the Resend account owner', async () => {
  const { d, sent } = deps({ config: async () => ({ mode: 'sandbox', api_key: 'k', from: 'B <onboarding@resend.dev>', sandbox_to: 'owner@x.io' }) })
  const res = await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), d)
  assert.deepEqual(await res.json(), { sent_to: 'owner@x.io' })
  assert.equal(sent[0].to, 'owner@x.io')
})

test('no test without email connected, without the right, or for someone else\'s campaign', async () => {
  assert.equal((await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), deps({ config: async () => null }).d)).status, 409)
  assert.equal((await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), deps({ canTest: async () => false }).d)).status, 403)
  assert.equal((await handleEmailTest(post({ campaign_id: '44444444-4444-4444-4444-444444444444' }), deps().d)).status, 404)
  assert.equal((await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), deps({ user: async () => null }).d)).status, 401)
})

test('a campaign without copy yet has nothing to test', async () => {
  const { d } = deps({ campaign: async () => ({ ...CAMPAIGN, copy_text: null }) })
  assert.equal((await handleEmailTest(post({ campaign_id: CAMPAIGN.id }), d)).status, 409)
})
