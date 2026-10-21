// Run: node --test supabase/functions/_shared/stripe.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { createHmac } from 'node:crypto'
import { test } from 'node:test'

import { formEncode, verifyStripeSignature } from './stripe.ts'

const secret = 'whsec_test_secret'
const body = '{"id":"evt_1","type":"checkout.session.completed"}'
const now = 1_760_000_000
const sign = (t: number, payload = body, key = secret) => createHmac('sha256', key).update(`${t}.${payload}`).digest('hex')

test('a valid signature passes', async () => {
  assert.equal(await verifyStripeSignature(body, `t=${now},v1=${sign(now)}`, secret, { now }), true)
})

test('any of several v1 signatures may match (secret rotation)', async () => {
  assert.equal(await verifyStripeSignature(body, `t=${now},v1=deadbeef,v1=${sign(now)}`, secret, { now }), true)
})

test('tampered body, wrong secret, missing header fail', async () => {
  assert.equal(await verifyStripeSignature(body + ' ', `t=${now},v1=${sign(now)}`, secret, { now }), false)
  assert.equal(await verifyStripeSignature(body, `t=${now},v1=${sign(now, body, 'other')}`, secret, { now }), false)
  assert.equal(await verifyStripeSignature(body, null, secret, { now }), false)
})

test('old timestamps are replay-protected', async () => {
  const old = now - 600
  assert.equal(await verifyStripeSignature(body, `t=${old},v1=${sign(old)}`, secret, { now }), false)
})

test('form encoding matches Stripe nested syntax', () => {
  assert.equal(
    formEncode({ mode: 'subscription', line_items: [{ price: 'price_1', quantity: 1 }], metadata: { org_id: 'o 1' } }),
    'mode=subscription&line_items%5B0%5D%5Bprice%5D=price_1&line_items%5B0%5D%5Bquantity%5D=1&metadata%5Borg_id%5D=o%201',
  )
})
