import { expect, test, type Page } from '@playwright/test'

// Decision intelligence in the UI, against a mocked backend: the
// recommendation at Gate 1 (with the approve-anyway reason rule), a blocked
// campaign, the Dashboard badge and the Tools "Should we advertise?" result.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()

const FACTORS = [
  { key: 'demand', weight: 0.25, score: 0.12, value: 'search interest 8 now, 6 on average (0-100)', source: 'Google Trends', reliability: 'measured', fetched_at: now, available: true, stale: false },
  { key: 'momentum', weight: 0.1, score: 0.55, value: 'latest is 1.3× the average, rising', source: 'Google Trends', reliability: 'measured', fetched_at: now, available: true, stale: false },
  { key: 'purchase_intent', weight: 0.2, score: 0, value: '0% of 14 posts/headlines talk about buying or comparing', source: 'Bluesky search', reliability: 'proxy', fetched_at: now, available: true, stale: false },
  { key: 'competition', weight: 0.15, score: 1, value: '0 recent news articles on the topic', source: 'NewsAPI', reliability: 'proxy', fetched_at: now, available: true, stale: false },
  { key: 'reachability', weight: 0.15, score: 0.33, value: '1 of 3 personas use a channel we post to (bluesky, email)', source: 'AI personas', reliability: 'estimate', available: true, stale: false },
  { key: 'track_record', weight: 0.15, score: null, value: '0 measured past campaign(s) in this category (need 2)', source: 'your campaign history', reliability: 'measured', available: false, stale: false },
]

function decision(over: Record<string, unknown> = {}) {
  return {
    id: 'd1', campaign_id: 'c1', decision: 'KILL', opportunity_score: 26, uncertainty: 0.15,
    reason_codes: ['WEAK_DEMAND', 'WEAK_PURCHASE_INTENT', 'LOW_COMPETITION', 'AUDIENCE_HARD_TO_REACH', 'NO_HISTORY'],
    factors: FACTORS, hard_blocks: [], review_flags: [], constraints: {}, reevaluate: null,
    baseline: { rule: 'launch whenever feasibility ≥ 40', decision: 'KILL' }, policy_version: 'decision-v1', trigger: 'initial',
    outcome: null, created_at: now, ...over,
  }
}

const CAMPAIGN = {
  id: 'c1', org_id: ORG.id, idea: 'Fax machine refurbishing service', domain_category: 'other', feasibility_score: 12, feasibility_rationale: 'thin',
  status: 'awaiting_gate_1', current_round: 1, reddit_subreddit: null, email_to: null, cta_url: null, use_image_template: false,
  use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
  stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
}

async function signIn(page: Page, rows: { campaign?: object; decisions?: object[] } = {}) {
  const votes: Record<string, unknown>[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const method = route.request().method()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role: 'owner', organizations: ORG }]
    else if (url.includes('/rpc/org_usage')) body = { plan: 'free', limits: {}, used: {} }
    else if (url.includes('/rpc/org_approval_policy')) body = { required_approvals: 1 }
    else if (url.includes('/rpc/')) body = null
    else if (url.includes('/campaigns?')) body = single ? rows.campaign ?? CAMPAIGN : [rows.campaign ?? CAMPAIGN]
    else if (url.includes('/campaign_decisions')) body = rows.decisions ?? [decision()]
    else if (url.includes('/gate_decisions')) body = { id: 'g1', campaign_id: 'c1', gate_number: 1, round_number: 1, decision: null, decided_at: null }
    else if (url.includes('/gate_approvals') && method === 'POST') {
      votes.push(route.request().postDataJSON())
      body = null
    }
    await route.fulfill({ status: method === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({
      access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600,
      user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
    }))
  }, USER)
  return votes
}

test('Gate 1 leads with the recommendation, and approving against it needs a reason', async ({ page }) => {
  const votes = await signIn(page)
  await page.goto('/campaigns/c1')
  const card = page.getByTestId('decision-card').first()
  await expect(card).toBeVisible()
  await expect(card.getByText("Don't run", { exact: true })).toBeVisible()
  await expect(card.getByText('Weak search demand')).toBeVisible()
  await expect(card.getByText('Purchase intent')).toBeVisible()
  await expect(card.getByText(/old rule/i)).toBeVisible()

  const approve = page.getByRole('button', { name: /^approve$/i })
  await expect(approve).toBeDisabled()
  await expect(page.getByText(/approving|approve anyway|why approve/i).first()).toBeVisible()
  await page.getByLabel(/why approve anyway/i).fill('Partner event already booked')
  await expect(approve).toBeEnabled()
  await approve.click()
  await expect.poll(() => votes.length).toBe(1)
  expect(votes[0]).toMatchObject({ decision: 'approve', comment: 'Partner event already booked' })
})

test('a launch recommendation needs no reason to approve', async ({ page }) => {
  await signIn(page, { decisions: [decision({ decision: 'LAUNCH', opportunity_score: 83, reason_codes: ['STRONG_DEMAND'] })] })
  await page.goto('/campaigns/c1')
  await expect(page.getByTestId('decision-card').first().getByText('Launch', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /^approve$/i })).toBeEnabled()
})

test('a blocked campaign says why and offers no approval', async ({ page }) => {
  await signIn(page, {
    campaign: { ...CAMPAIGN, idea: 'Online store selling pistols', status: 'blocked' },
    decisions: [decision({ hard_blocks: [{ code: 'PROHIBITED_PRODUCT', detail: '"pistols": ad platforms don\'t allow advertising weapons or ammunition' }], reason_codes: ['PROHIBITED_PRODUCT'], opportunity_score: 82 })],
  })
  await page.goto('/campaigns/c1')
  await expect(page.getByRole('heading', { name: /stopped before gate 1/i })).toBeVisible()
  await expect(page.getByText('Prohibited product').first()).toBeVisible()
  await expect(page.getByText(/ad platforms don't allow advertising weapons/i).first()).toBeVisible()
  await expect(page.getByRole('button', { name: /^approve$/i })).toHaveCount(0)
})

test('the dashboard shows each campaign’s verdict', async ({ page }) => {
  await signIn(page, { decisions: [decision({ decision: 'TEST_SMALL' })] })
  await page.goto('/dashboard')
  await expect(page.getByText('Test small').first()).toBeVisible()
})

test('Tools: "Should we advertise?" shows the decision with its evidence', async ({ page }) => {
  await signIn(page)
  await page.route('**/rest/v1/capability_runs?*', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(/id=eq\./.test(route.request().url())
        ? { id: 'r1', capability: 'decision', status: 'completed', params: { idea: 'Fax repairs' }, result: decision({ decision: 'WAIT', reevaluate: { type: 'trend_threshold', keyword: 'fax repairs', threshold: 30 } }), error: null, created_at: now }
        : []),
    }),
  )
  await page.goto('/tools?run=r1')
  const card = page.getByTestId('decision-card')
  await expect(card.getByText('Wait', { exact: true })).toBeVisible()
  await expect(card.getByText(/re-checked automatically/i)).toBeVisible()
})

test('the decision card fits a small phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 })
  await signIn(page)
  await page.goto('/campaigns/c1')
  await expect(page.getByTestId('decision-card').first()).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
