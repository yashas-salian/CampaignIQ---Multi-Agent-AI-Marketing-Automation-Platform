import { expect, test, type Page } from '@playwright/test'

// The circuit breaker in the UI, against a mocked backend: a paused campaign
// leads with what tripped and how to resume (owners/admins only, with a note),
// the safety controls (offer end date, emergency stop, revoke), and the
// Dashboard's paused pill.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()
const hourAgo = new Date(Date.now() - 3600_000).toISOString()

const CAMPAIGN = {
  id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee for commuters', domain_category: 'food_beverage', feasibility_score: 60, feasibility_rationale: 'ok',
  status: 'awaiting_metrics', current_round: 1, reddit_subreddit: null, email_to: null, cta_url: 'https://brew.example', use_image_template: false,
  use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: now,
  stop_requested: false, target_language: 'en', created_at: now, updated_at: now, offer_ends_at: hourAgo, paused_at: now,
}
const HOLD = {
  id: 'h1', campaign_id: 'c1', channel: null, trigger: 'EXPIRED_OFFER', severity: 'critical', status: 'active',
  detail: 'The offer ended 1 hour ago; sends still promoted it.', evidence: { offer_ends_at: hourAgo }, signal_at: hourAgo,
  created_at: now, resolved_at: null, resolution_note: null,
}
const NEWS = {
  ...HOLD, id: 'h2', trigger: 'BRAND_RISK', severity: 'warning', detail: 'Two separate crisis headlines about order-ahead coffee.',
  evidence: { headlines: ['Coffee chain faces lawsuit over order ahead app outage', 'Order-ahead coffee apps hit by data breach'] },
}
const PAST = { ...HOLD, id: 'h0', trigger: 'INVALID_DESTINATION', status: 'false_alarm', resolved_at: hourAgo, resolution_note: 'The page was only down for a deploy' }

async function signIn(page: Page, opts: { role?: string; campaign?: object; holds?: object[] } = {}) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  const campaign = opts.campaign ?? CAMPAIGN
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role: opts.role ?? 'owner', organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc) {
      if (['resolve_hold', 'emergency_stop', 'revoke_approval', 'set_offer_end'].includes(rpc)) rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = null
    } else if (url.includes('/campaigns?')) body = single ? campaign : [campaign]
    else if (url.includes('/campaign_holds')) body = opts.holds ?? [HOLD, PAST]
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
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
  return { rpcs }
}

test('a paused campaign leads with what tripped, the evidence and how to resume', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/campaigns/c1')
  const panel = page.getByTestId('paused-panel')
  await expect(panel.getByRole('heading', { name: 'This campaign is paused' })).toBeVisible()
  await expect(page.getByTestId('paused-pill')).toHaveText('Paused')
  await expect(panel.getByText('The offer has ended')).toBeVisible()
  await expect(panel.getByText('Every channel')).toBeVisible()
  await expect(panel.getByText(/Extend the offer's end date/)).toBeVisible()
  await expect(panel.getByText(/already went out stay up/)).toBeVisible()

  const resume = panel.getByRole('button', { name: 'Resume sends' })
  await expect(resume).toBeDisabled()
  await panel.getByLabel(/what did you check/i).fill('Offer extended to 30 November')
  await resume.click()
  await expect.poll(() => rpcs.length).toBe(1)
  expect(rpcs[0]).toEqual({ name: 'resolve_hold', args: { p_hold: 'h1', p_note: 'Offer extended to 30 November', p_false_alarm: false } })
})

test('only owners and admins see the resume form', async ({ page }) => {
  await signIn(page, { role: 'approver' })
  await page.goto('/campaigns/c1')
  const panel = page.getByTestId('paused-panel')
  await expect(panel.getByText(/only owners and admins can resume/i)).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Resume sends' })).toHaveCount(0)
})

test('a warning shows its headlines without pausing anything', async ({ page }) => {
  const { rpcs } = await signIn(page, { campaign: { ...CAMPAIGN, paused_at: null }, holds: [NEWS] })
  await page.goto('/campaigns/c1')
  const panel = page.getByTestId('paused-panel')
  await expect(panel.getByRole('heading', { name: /worth a look/i })).toBeVisible()
  await expect(panel.getByText(/data breach/)).toBeVisible()
  await expect(page.getByTestId('paused-pill')).toHaveCount(0)
  await panel.getByLabel(/what did you check/i).fill('Those stories are about another brand')
  await panel.getByRole('button', { name: /false alarm/i }).click()
  await expect.poll(() => rpcs[0]?.args.p_false_alarm).toBe(true)
})

test('safety controls: offer end date, emergency stop with a reason, revoke, and past holds', async ({ page }) => {
  const { rpcs } = await signIn(page, { campaign: { ...CAMPAIGN, paused_at: null, offer_ends_at: null }, holds: [PAST] })
  await page.goto('/campaigns/c1')
  await expect(page.getByTestId('paused-panel')).toHaveCount(0)
  const controls = page.getByTestId('safety-controls')

  await controls.getByLabel('Offer ends').fill('2026-11-30T23:59')
  await controls.getByRole('button', { name: 'Save end date' }).click()
  await expect.poll(() => rpcs.length).toBe(1)
  expect(rpcs[0].name).toBe('set_offer_end')
  expect(rpcs[0].args.p_ends_at).toBe(new Date('2026-11-30T23:59').toISOString())

  const stop = controls.getByRole('button', { name: 'Emergency stop' })
  await expect(stop).toBeDisabled()
  await controls.getByLabel(/why stop/i).fill('Our supplier just recalled this batch')
  await stop.click()
  await expect.poll(() => rpcs.length).toBe(2)
  expect(rpcs[1]).toEqual({ name: 'emergency_stop', args: { p_campaign: 'c1', p_reason: 'Our supplier just recalled this batch' } })

  await controls.getByLabel(/why stop/i).fill('The copy still mentions the old price')
  await controls.getByRole('button', { name: 'Revoke approval' }).click()
  await expect.poll(() => rpcs.length).toBe(3)
  expect(rpcs[2].name).toBe('revoke_approval')

  await controls.getByText('1 earlier hold').click()
  await expect(controls.getByText(/The page was only down for a deploy/)).toBeVisible()
})

test('viewers see the controls but cannot stop or edit', async ({ page }) => {
  await signIn(page, { role: 'viewer', campaign: { ...CAMPAIGN, paused_at: null }, holds: [] })
  await page.goto('/campaigns/c1')
  const controls = page.getByTestId('safety-controls')
  await expect(controls.getByText(/owners, admins and approvers can stop/i)).toBeVisible()
  await expect(controls.getByRole('button', { name: 'Emergency stop' })).toHaveCount(0)
  await expect(controls.getByLabel('Offer ends')).toBeDisabled()
})

test('the Dashboard marks a paused campaign', async ({ page }) => {
  await signIn(page)
  await page.goto('/dashboard')
  await expect(page.getByTestId('paused-pill').first()).toHaveText('Paused')
})

// Review screenshots: CB_SHOTS=<dir> npx playwright test e2e/circuit.spec.ts -g screenshots
test('screenshots of the paused panel and the safety controls', async ({ page }, info) => {
  const dir = process.env.CB_SHOTS
  test.skip(!dir, 'set CB_SHOTS to a folder to capture them')
  await signIn(page, { holds: [HOLD, NEWS, PAST] })
  await page.goto('/campaigns/c1')
  await page.getByTestId('paused-panel').screenshot({ path: `${dir}/cb-paused-${info.project.name}.png` })
  await page.getByTestId('safety-controls').screenshot({ path: `${dir}/cb-controls-${info.project.name}.png` })
})

test('the paused panel fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page, { holds: [HOLD, NEWS, PAST] })
  await page.goto('/campaigns/c1')
  await expect(page.getByTestId('paused-panel')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
