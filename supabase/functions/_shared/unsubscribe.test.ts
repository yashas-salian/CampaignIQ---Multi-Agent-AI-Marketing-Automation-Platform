// Run: node --test supabase/functions/_shared/unsubscribe.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { handleUnsubscribe, type UnsubscribeDb } from './unsubscribe.ts'

const TOKEN = 'a'.repeat(32)
const APP = 'https://campaigniq.app'

function db(known = true) {
  const calls: string[] = []
  const store: UnsubscribeDb = {
    async info(t) {
      calls.push(`info:${t}`)
      return known ? { brand: 'Brewline', slug: 'brewline', status: 'subscribed', language: 'fr', privacy_url: null } : null
    },
    async unsubscribe(t) {
      calls.push(`unsubscribe:${t}`)
      return known ? { status: 'unsubscribed', brand: 'Brewline' } : null
    },
    async erase(t) {
      calls.push(`erase:${t}`)
      return known ? { status: 'erased', brand: 'Brewline' } : null
    },
  }
  return { store, calls }
}

const post = (body: string, type: string, token = TOKEN) =>
  new Request(`https://x.supabase.co/functions/v1/unsubscribe?t=${token}`, { method: 'POST', body, headers: { 'Content-Type': type } })

test('the link in the email opens the brand\'s unsubscribe page on the website', async () => {
  const { store, calls } = db()
  const res = await handleUnsubscribe(new Request(`https://x.supabase.co/functions/v1/unsubscribe?t=${TOKEN}`), store, APP)
  assert.equal(res.status, 302)
  assert.equal(res.headers.get('Location'), `${APP}/unsubscribe?t=${TOKEN}`)
  assert.deepEqual(calls, []) // opening the link never unsubscribes by itself (mail scanners follow links)
})

test('one-click (RFC 8058): a POST of List-Unsubscribe=One-Click unsubscribes and answers 200 with an empty body', async () => {
  const { store, calls } = db()
  const res = await handleUnsubscribe(post('List-Unsubscribe=One-Click', 'application/x-www-form-urlencoded'), store, APP)
  assert.equal(res.status, 200)
  assert.equal(await res.text(), '')
  assert.deepEqual(calls, [`unsubscribe:${TOKEN}`])
})

test('one-click with an unknown token still answers 200 and reveals nothing', async () => {
  const { store } = db(false)
  const res = await handleUnsubscribe(post('List-Unsubscribe=One-Click', 'application/x-www-form-urlencoded'), store, APP)
  assert.equal(res.status, 200)
  assert.equal(await res.text(), '')
})

test('the page asks who it is for, then unsubscribes when the person presses the button', async () => {
  const { store } = db()
  const info = await handleUnsubscribe(post(JSON.stringify({ t: TOKEN, action: 'info' }), 'application/json'), store, APP)
  assert.deepEqual(await info.json(), { brand: 'Brewline', slug: 'brewline', status: 'subscribed', language: 'fr', privacy_url: null })
  const done = await handleUnsubscribe(post(JSON.stringify({ t: TOKEN, action: 'unsubscribe' }), 'application/json'), store, APP)
  assert.deepEqual(await done.json(), { status: 'unsubscribed', brand: 'Brewline' })
})

test('an unknown token on the page is a plain 404', async () => {
  const { store } = db(false)
  const res = await handleUnsubscribe(post(JSON.stringify({ t: TOKEN, action: 'info' }), 'application/json'), store, APP)
  assert.equal(res.status, 404)
})

test('a malformed token is refused before the database is asked', async () => {
  const { store, calls } = db()
  const res = await handleUnsubscribe(post('List-Unsubscribe=One-Click', 'application/x-www-form-urlencoded', 'nope'), store, APP)
  assert.equal(res.status, 400)
  assert.deepEqual(calls, [])
})

test('someone can delete their own details from the page (after unsubscribing)', async () => {
  const { store, calls } = db()
  const res = await handleUnsubscribe(post(JSON.stringify({ t: TOKEN, action: 'erase' }), 'application/json'), store, APP)
  assert.deepEqual(await res.json(), { status: 'erased', brand: 'Brewline' })
  assert.deepEqual(calls, [`unsubscribe:${TOKEN}`, `erase:${TOKEN}`])  // unsubscribed first, then erased
})
