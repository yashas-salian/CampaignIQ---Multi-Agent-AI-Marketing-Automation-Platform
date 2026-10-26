// Run: node --test supabase/functions/_shared/signup.test.ts   (Node 24+, native TS)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { confirmationEmail, handleJoin, type JoinDeps } from './signup.ts'

const APP = 'https://campaigniq.app'
const WORDING = 'Yes, send me marketing emails from Brewline. I can unsubscribe any time.'

function deps(signupAction = 'confirm_email', over: Partial<JoinDeps> = {}) {
  const sent: { org: string; to: string; subject: string; html: string }[] = []
  const calls: string[] = []
  const d: JoinDeps = {
    async info(slug) {
      calls.push(`info:${slug}`)
      return slug === 'brewline' ? { brand: 'Brewline', slug, privacy_url: null, brand_color: '#ff6b3d', logo_path: null, open: true } : null
    },
    async signup(args) {
      calls.push(`signup:${args.email}:${args.ip}`)
      return { action: signupAction, token: 'f'.repeat(32), email: args.email, org_id: 'o1', first_name: args.firstName, language: args.language }
    },
    async confirm(token) {
      calls.push(`confirm:${token}`)
      return token === 'a'.repeat(32) ? { status: 'subscribed', brand: 'Brewline' } : null
    },
    async resubscribe(t) {
      calls.push(`resubscribe:${t}`)
      return { action: 'confirm_email', token: 'e'.repeat(32), email: 'a@x.io', org_id: 'o1', first_name: null, language: 'fr' }
    },
    async sender(org) {
      return { brand: 'Brewline', postalAddress: '12 Bean St, Pune', mode: 'live' as const, sandboxTo: null }
    },
    async send(org, to, subject, html) {
      sent.push({ org, to, subject, html })
    },
    async recordSystemEmail() {
      calls.push('counted')
    },
    ...over,
  }
  return { d, sent, calls }
}

const post = (body: object, ip = '203.0.113.7') =>
  new Request('https://x.supabase.co/functions/v1/join', {
    method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json', 'x-forwarded-for': `${ip}, 10.0.0.1` },
  })

test('the form page learns the brand; an unknown brand is a 404', async () => {
  const { d } = deps()
  assert.equal((await (await handleJoin(post({ action: 'info', slug: 'brewline' }), d, APP)).json()).brand, 'Brewline')
  assert.equal((await handleJoin(post({ action: 'info', slug: 'nope' }), d, APP)).status, 404)
})

test('signing up sends one confirmation email through the brand\'s account, in the person\'s language', async () => {
  const { d, sent, calls } = deps()
  const res = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'ana@example.com', first_name: 'Ana', language: 'fr',
    consent_text: WORDING, c: '33333333-3333-3333-3333-333333333333' }), d, APP)
  assert.deepEqual(await res.json(), { status: 'check_inbox' })
  assert.equal(sent.length, 1)
  assert.equal(sent[0].to, 'ana@example.com')
  assert.match(sent[0].subject, /Brewline/)
  assert.ok(sent[0].html.includes(`${APP}/confirm?token=${'f'.repeat(32)}`))
  assert.ok(sent[0].html.includes('Confirmer'))  // French
  assert.ok(calls.includes('signup:ana@example.com:203.0.113.7') && calls.includes('counted'))
})

test('the answer never tells whether someone is already on the list', async () => {
  for (const action of ['already', 'blocked']) {
    const { d, sent } = deps(action)
    const res = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'a@x.io', consent_text: WORDING }), d, APP)
    assert.deepEqual(await res.json(), { status: 'check_inbox' })
    assert.equal(sent.length, 0)
  }
})

test('a bot filling the hidden field is told it worked, and nothing happens', async () => {
  const { d, sent, calls } = deps()
  const res = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'bot@x.io', consent_text: WORDING, company: 'Spam Inc' }), d, APP)
  assert.deepEqual(await res.json(), { status: 'check_inbox' })
  assert.equal(sent.length, 0)
  assert.ok(!calls.some((c) => c.startsWith('signup')))
})

test('closed, rate-limited and invalid sign-ups say so', async () => {
  assert.deepEqual(await (await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'a@x.io', consent_text: WORDING }), deps('closed').d, APP)).json(), { status: 'closed' })
  const limited = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'a@x.io', consent_text: WORDING }), deps('rate_limited').d, APP)
  assert.equal(limited.status, 429)
  const noWording = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'a@x.io' }), deps().d, APP)
  assert.equal(noWording.status, 400)
})

test('in sandbox mode the confirmation goes to the account owner, labelled', async () => {
  const { d, sent } = deps('confirm_email', { sender: async () => ({ brand: 'Brewline', postalAddress: 'x', mode: 'sandbox' as const, sandboxTo: 'owner@x.io' }) })
  await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'ana@example.com', consent_text: WORDING }), d, APP)
  assert.equal(sent[0].to, 'owner@x.io')
  assert.match(sent[0].subject, /^\[Sandbox: for ana@example.com\]/)
})

test('a sending failure is reported, so the person can try again', async () => {
  const { d } = deps('confirm_email', { send: async () => { throw new Error('rate limited') } })
  const res = await handleJoin(post({ action: 'signup', slug: 'brewline', email: 'a@x.io', consent_text: WORDING }), d, APP)
  assert.equal(res.status, 503)
})

test('the confirmation link subscribes; an unknown or expired one is a 404', async () => {
  const { d } = deps()
  assert.deepEqual(await (await handleJoin(post({ action: 'confirm', token: 'a'.repeat(32) }), d, APP)).json(), { status: 'subscribed', brand: 'Brewline' })
  assert.equal((await handleJoin(post({ action: 'confirm', token: 'b'.repeat(32) }), d, APP)).status, 404)
})

test('resubscribing from an unsubscribe link sends a fresh confirmation', async () => {
  const { d, sent } = deps()
  const res = await handleJoin(post({ action: 'resubscribe', t: 'c'.repeat(32) }), d, APP)
  assert.deepEqual(await res.json(), { status: 'check_inbox' })
  assert.equal(sent[0].to, 'a@x.io')
})

test('the confirmation email has the brand, the link, the address and an ignore-me line', () => {
  const { subject, html } = confirmationEmail({ brand: 'Brew & Co', firstName: '<Ana>', language: 'en', link: 'https://x/confirm?token=1', postalAddress: '12 Bean St' })
  assert.equal(subject, 'Confirm your subscription to Brew & Co')
  assert.ok(html.includes('Hi &lt;Ana&gt;,') && html.includes('href="https://x/confirm?token=1"') && html.includes('12 Bean St'))
  assert.ok(html.includes("didn't sign up"))
})
