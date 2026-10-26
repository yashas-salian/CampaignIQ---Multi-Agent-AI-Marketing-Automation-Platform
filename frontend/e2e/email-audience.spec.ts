import { expect, test, type Page } from '@playwright/test'

// Who a campaign emails, against a mocked backend: saved segments on the
// Contacts page, picking one at Gate 1 (with how many people it reaches), the
// progress line once Gate 1 fixed the audience, the note when no Resend account
// is connected, and the public unsubscribe page a brand's customer lands on.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Brewline', personal: false }
const now = new Date().toISOString()
const LIVE = { connected: true, mode: 'live', domain: 'brewline.coffee', from_email: 'hello@brewline.coffee', from_name: 'Brewline',
  sandbox_to: null, webhook: true, webhook_ok_at: null, daily_limit: 100, send_window_start: 9, send_window_end: 20, timezone: 'UTC',
  paused_reason: null, connected_at: now, postal_address: true, privacy_url: true, slug: 'brewline' }
const SEGMENTS = [{ id: 's1', org_id: ORG.id, name: 'Coffee buyers', filter: { tags_any: ['coffee'], purchased_within_days: 90 }, created_at: now }]
const CAMPAIGN = { id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee', domain_category: 'food_beverage', feasibility_score: 60,
  feasibility_rationale: 'ok', status: 'awaiting_gate_1', current_round: 1, email_to: null, cta_url: null, max_rounds: 3,
  campaign_summary: null, stop_requested: false, target_language: 'en', segment_id: null, email_audience_frozen_at: null,
  created_at: now, updated_at: now }

interface Setup { role?: string; status?: object; campaign?: object; progress?: object; gate?: number; rounds?: object[] }

async function signIn(page: Page, s: Setup = {}) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  const writes: { url: string; method: string; body: unknown }[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const req = route.request()
    const url = req.url()
    const single = (req.headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role: s.role ?? 'owner', organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc === 'org_approval_policy') body = { required_approvals: 1 }
    else if (rpc === 'email_status') body = s.status ?? LIVE
    else if (rpc === 'segment_count') body = 42
    else if (rpc === 'contact_counts') body = { total: 50, subscribed: 42, pending: 0, unsubscribed: 8, bounced: 0, complained: 0, cap: 1000 }
    else if (rpc === 'contact_tags') body = [{ tag: 'coffee', people: 40 }, { tag: 'tea', people: 9 }]
    else if (rpc === 'email_round_stats') body = s.rounds ?? []
    else if (rpc === 'audience_progress') body = s.progress ?? { total: 120, emailed: 40, remaining: 60, holdout: 10, excluded: 0, waiting: 10 }
    else if (rpc) {
      rpcs.push({ name: rpc, args: req.postDataJSON() })
      body = null
    } else if (url.includes('/segments')) {
      if (req.method() !== 'GET') writes.push({ url, method: req.method(), body: req.postDataJSON() })
      body = SEGMENTS
    } else if (url.includes('/campaigns?')) body = single ? (s.campaign ?? CAMPAIGN) : [s.campaign ?? CAMPAIGN]
    else if (url.includes('/gate_decisions')) body = { id: 'g1', campaign_id: 'c1', gate_number: s.gate ?? 1, round_number: 1, decision: null, decided_at: null }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/storage/v1/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({
      access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600,
      user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
    }))
  }, USER)
  return { rpcs, writes }
}

test('segments: saved filters with how many people each reaches; a new one is built from tags and purchases', async ({ page }) => {
  const { writes } = await signIn(page, { role: 'marketer' })
  await page.goto('/contacts')
  const panel = page.getByTestId('segments')
  await expect(panel.getByTestId('segment-s1')).toContainText('Coffee buyers', { timeout: 15_000 })
  await expect(panel.getByTestId('segment-s1')).toContainText('tagged coffee · bought in the last 90 days')
  await expect(panel.getByTestId('segment-s1')).toContainText('42 people now')
  await panel.getByRole('button', { name: 'New segment' }).click()
  const editor = panel.getByTestId('segment-editor')
  await editor.getByLabel('Name').fill('Lapsed tea fans')
  await editor.getByRole('group', { name: 'Has any of these tags' }).getByRole('button', { name: 'tea' }).click()
  await editor.getByLabel(/Hasn't bought in/).fill('180')
  await expect(editor.getByTestId('segment-count')).toHaveText('42 people now')
  await editor.getByRole('button', { name: 'Save segment' }).click()
  await expect.poll(() => writes.length).toBe(1)
  expect(writes[0].body).toMatchObject({ org_id: ORG.id, name: 'Lapsed tea fans', filter: { tags_any: ['tea'], not_purchased_within_days: 180 } })
})

test('Gate 1: pick who gets the email, with the count, before the audience is fixed', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/campaigns/c1')
  const audience = page.getByTestId('email-audience')
  await expect(audience).toBeVisible({ timeout: 15_000 })
  await audience.getByRole('combobox', { name: 'Who gets the email' }).click()
  await page.getByRole('option', { name: 'Coffee buyers' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'set_campaign_segment')?.args).toEqual({ p_campaign: 'c1', p_segment: 's1' })
})

test('Gate 1 with a segment chosen shows what it means and how many people it reaches', async ({ page }) => {
  await signIn(page, { campaign: { ...CAMPAIGN, segment_id: 's1' } })
  await page.goto('/campaigns/c1')
  const audience = page.getByTestId('email-audience')
  await expect(audience).toContainText('tagged coffee · bought in the last 90 days', { timeout: 15_000 })
  await expect(audience).toContainText('42 people now')
  await expect(audience.getByRole('link', { name: 'Manage segments' })).toHaveAttribute('href', '/contacts#segments')
})

test('once Gate 1 fixed the audience, the campaign shows how far the batches have got', async ({ page }) => {
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'awaiting_metrics', segment_id: 's1', email_audience_frozen_at: now } })
  await page.goto('/campaigns/c1')
  const audience = page.getByTestId('email-audience')
  await expect(audience).toContainText('Coffee buyers: 40 of 110 people emailed, 60 still to go', { timeout: 15_000 })
  await expect(audience).toContainText('10 waiting for the sending window')
  await expect(audience).toContainText('10 held back for the impact test')
  await expect(audience.getByRole('combobox')).toHaveCount(0)
})

test('without a connected Resend account, Gate 1 says email goes to the test inbox', async ({ page }) => {
  await signIn(page, { status: { ...LIVE, connected: false, mode: null } })
  await page.goto('/campaigns/c1')
  const audience = page.getByTestId('email-audience')
  await expect(audience).toContainText('test inbox', { timeout: 15_000 })
  await expect(audience.getByRole('link', { name: 'Connect it' })).toHaveAttribute('href', '/settings#email')
})

test('unsubscribe page: in the person\'s language, one button, then done', async ({ page }) => {
  const token = 'a'.repeat(32)
  const actions: string[] = []
  await page.route('**/functions/v1/unsubscribe', async (route) => {
    const body = route.request().postDataJSON()
    actions.push(body.action)
    const payload = body.action === 'info'
      ? { brand: 'Brewline', slug: 'brewline', status: 'subscribed', language: 'fr', privacy_url: 'https://brewline.coffee/privacy' }
      : { status: 'unsubscribed', brand: 'Brewline' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  await page.goto(`/unsubscribe?t=${token}`)
  await expect(page.getByRole('heading', { name: 'Se désabonner de Brewline ?' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('navigation')).toHaveCount(0) // no CampaignIQ chrome for a brand's customer
  expect(actions).toEqual(['info']) // opening the page never unsubscribes
  await page.getByRole('button', { name: 'Me désabonner' }).click()
  await expect(page.getByRole('heading', { name: 'Vous êtes désabonné' })).toBeVisible()
  expect(actions).toEqual(['info', 'unsubscribe'])
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('a broken unsubscribe link says so', async ({ page }) => {
  await page.goto('/unsubscribe?t=nope')
  await expect(page.getByRole('heading', { name: "This link doesn't work" })).toBeVisible({ timeout: 15_000 })
})

test('Gate 1: the sign-up link on posts can be switched off for this campaign', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/campaigns/c1')
  const link = page.getByTestId('email-audience').getByRole('checkbox', { name: /sign-up link/ })
  await expect(link).toBeChecked({ timeout: 15_000 })
  await link.click()  // the box follows the saved campaign, so only the call is checked here
  await expect.poll(() => rpcs.find((r) => r.name === 'set_campaign_signup_link')?.args).toEqual({ p_campaign: 'c1', p_on: false })
})

async function joinRoutes(page: Page, over: Record<string, (body: Record<string, unknown>) => [number, object]> = {}) {
  const calls: Record<string, unknown>[] = []
  await page.route('**/functions/v1/join', async (route) => {
    const body = route.request().postDataJSON()
    calls.push(body)
    const handlers: Record<string, (b: Record<string, unknown>) => [number, object]> = {
      info: () => [200, { brand: 'Brewline', slug: 'brewline', privacy_url: 'https://brewline.coffee/privacy', brand_color: '#c2410c', logo_path: null, open: true }],
      signup: () => [200, { status: 'check_inbox' }],
      confirm: (b) => (b.token === 'a'.repeat(32) ? [200, { status: 'subscribed', brand: 'Brewline' }] : [404, { error: 'not found' }]),
      resubscribe: () => [200, { status: 'check_inbox' }],
      ...over,
    }
    const [status, payload] = handlers[String(body.action)](body)
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  return calls
}

test('sign-up form: the wording shown is what gets recorded, a campaign is credited, then check your inbox', async ({ page }) => {
  const calls = await joinRoutes(page)
  await page.goto('/join/brewline?c=33333333-3333-3333-3333-333333333333')
  await expect(page.getByRole('heading', { name: 'Get emails from Brewline' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await page.getByLabel('Email').fill('ana@example.com')
  await page.getByLabel('First name (optional)').fill('Ana')
  await page.getByRole('button', { name: 'Sign up' }).click()
  await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible()
  const signup = calls.find((c) => c.action === 'signup')!
  expect(signup).toMatchObject({ slug: 'brewline', email: 'ana@example.com', first_name: 'Ana', c: '33333333-3333-3333-3333-333333333333', company: '' })
  expect(signup.consent_text).toBe('Yes, send me marketing emails from Brewline. I can unsubscribe any time with the link in every email.')
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('sign-up form: closed when the brand is not taking sign-ups', async ({ page }) => {
  await joinRoutes(page, { info: () => [200, { brand: 'Brewline', slug: 'brewline', privacy_url: null, brand_color: null, logo_path: null, open: false }] })
  await page.goto('/join/brewline')
  await expect(page.getByRole('heading', { name: 'Sign-ups are closed' })).toBeVisible({ timeout: 15_000 })
})

test('the confirmation link subscribes; an expired one says how to get a new one', async ({ page }) => {
  await joinRoutes(page)
  await page.goto(`/confirm?token=${'a'.repeat(32)}`)
  await expect(page.getByRole('heading', { name: "You're subscribed" })).toBeVisible({ timeout: 15_000 })
  await page.goto(`/confirm?token=${'b'.repeat(32)}`)
  await expect(page.getByRole('heading', { name: "This link doesn't work" })).toBeVisible({ timeout: 15_000 })
})

test('after unsubscribing, someone can change their mind: a fresh confirmation is sent', async ({ page }) => {
  const calls = await joinRoutes(page)
  await page.route('**/functions/v1/unsubscribe', (route) => route.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ brand: 'Brewline', slug: 'brewline', status: 'unsubscribed', language: 'en', privacy_url: null }) }))
  await page.goto(`/unsubscribe?t=${'c'.repeat(32)}`)
  await page.getByRole('button', { name: 'Changed your mind? Resubscribe' }).click({ timeout: 15_000 })
  await expect(page.getByRole('heading', { name: 'Check your inbox' })).toBeVisible()
  expect(calls.find((c) => c.action === 'resubscribe')).toEqual({ action: 'resubscribe', t: 'c'.repeat(32) })
})

test('after unsubscribing, someone can delete their details too (asked twice)', async ({ page }) => {
  const actions: string[] = []
  await page.route('**/functions/v1/unsubscribe', async (route) => {
    const body = route.request().postDataJSON()
    actions.push(body.action)
    const payload = body.action === 'info'
      ? { brand: 'Brewline', slug: 'brewline', status: 'unsubscribed', language: 'en', privacy_url: null }
      : { status: 'erased', brand: 'Brewline' }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  await page.goto(`/unsubscribe?t=${'d'.repeat(32)}`)
  await page.getByRole('button', { name: 'Also delete my details' }).click({ timeout: 15_000 })
  expect(actions).toEqual(['info'])
  await page.getByRole('button', { name: 'Yes, delete everything Brewline has about me' }).click()
  await expect(page.getByRole('heading', { name: 'Your details are deleted' })).toBeVisible()
  expect(actions).toEqual(['info', 'erase'])
})

test('Gate 1 shows the AI-suggested audience, and using it is one click', async ({ page }) => {
  const suggestion = { filter: { tags_any: ['coffee'], purchased_within_days: 90 }, reason: 'Recent coffee buyers match the commuter persona.', people: 120 }
  const { rpcs } = await signIn(page, { campaign: { ...CAMPAIGN, email_suggestion: suggestion } })
  await page.goto('/campaigns/c1')
  const card = page.getByTestId('email-suggestion')
  await expect(card).toContainText('AI suggestion: tagged coffee · bought in the last 90 days · 120 people now', { timeout: 15_000 })
  await expect(card).toContainText('Recent coffee buyers match the commuter persona.')
  await card.getByRole('button', { name: 'Use this audience' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'accept_email_suggestion')?.args).toEqual({ p_campaign: 'c1' })
})

test('Gate 2: the coming batch, why people left, each round so far, and a test email to yourself', async ({ page }) => {
  const tests: unknown[] = []
  await page.route('**/functions/v1/email-test', async (route) => {
    tests.push(route.request().postDataJSON())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sent_to: 'ava@example.com' }) })
  })
  await signIn(page, {
    gate: 2,
    campaign: { ...CAMPAIGN, status: 'awaiting_gate_2', current_round: 2, max_rounds: 3, segment_id: 's1', email_audience_frozen_at: now },
    progress: { total: 130, emailed: 40, remaining: 80, holdout: 0, excluded: 3, waiting: 0, excluded_by: { unsubscribed: 2, inactive: 1 } },
    rounds: [{ round_number: 1, channel: 'email', sent: 40, delivered: 38, bounced: 1, complained: 0, waiting: 0, sandbox: false }],
  })
  await page.goto('/campaigns/c1')
  const audience = page.getByTestId('email-audience').first()
  await expect(audience.getByTestId('next-batch')).toContainText('This round emails about 40 people.', { timeout: 15_000 })
  await expect(audience.getByTestId('next-batch')).toContainText('Sent between 09:00 and 20:00 (UTC), up to 100 a day')
  await expect(audience).toContainText('Left the audience since: 2 unsubscribed, 1 inactive')
  await expect(audience.getByTestId('email-rounds')).toContainText('Round 1: 40 sent · 38 delivered · 1 bounced · 0 spam reports')
  await audience.getByRole('button', { name: 'Send me a test' }).click()
  await expect(page.getByText('Test sent to ava@example.com')).toBeVisible()
  expect(tests).toEqual([{ campaign_id: 'c1' }])
})
