import { expect, test, type Page } from '@playwright/test'

// The crash test in the UI, against a mocked backend: the Gate 2 report with
// the marked ad and findings, the revised version (use it), the critical-risk
// reason rule, and the Tools "Crash-test an ad" result.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()

const AD = {
  body: 'Rahul says the moment he steps off the metro, his coffee is waiting. Grab your first order free before the early-bird spots run out.',
  headline: 'Your coffee ready on arrival',
  cta: 'Order Now',
}
const REVISED = { body: 'Step off the metro and your coffee is waiting. Your first order is free.', headline: 'Coffee ready when you arrive', cta: 'Order now' }
const FINDINGS = [
  { key: 'rule:-:INVENTED_TESTIMONIAL:rahul says', source: 'rule', scenario: null, type: 'INVENTED_TESTIMONIAL', severity: 'critical', quote: 'Rahul says', field: 'body', problem: 'Presents a customer quote the brand has not provided (FTC 16 CFR 465).', fix: 'Remove it.' },
  { key: 'rule:-:FALSE_URGENCY:run out', source: 'rule', scenario: null, type: 'FALSE_URGENCY', severity: 'high', quote: 'run out', field: 'body', problem: 'Creates urgency the brand never stated.', fix: 'Remove the scarcity.' },
  { key: 'simulation:price_sensitive:PRICE_OBJECTION:', source: 'simulation', scenario: 'price_sensitive', type: 'PRICE_OBJECTION', severity: 'medium', quote: null, field: null, problem: 'What does it cost after the first order?', fix: 'Say it plainly.' },
]
const AFTER = [
  { key: 'simulation:price_sensitive:PRICE_OBJECTION:', source: 'simulation', scenario: 'price_sensitive', type: 'PRICE_OBJECTION', severity: 'low', quote: null, field: null, problem: 'Still no price after the first order.', fix: '' },
]
function report(over: Record<string, unknown> = {}) {
  return {
    scenario_set: 'marketing-risk-v1', rules_version: 'rules-v1', simulation_only: true, status: 'COMPLETED', ad: AD,
    findings: FINDINGS, risk: 'critical', counts: { low: 0, medium: 1, high: 1, critical: 1 },
    revised: REVISED, revision_notes: ['Removed the invented customer quote', 'Removed the made-up scarcity'],
    revised_findings: AFTER, revised_risk: 'low',
    comparison: { resolved: [FINDINGS[0].key, FINDINGS[1].key], remaining: [AFTER[0].key], new: [] }, note: '', created_at: now, ...over,
  }
}
function crashRow(over: Record<string, unknown> = {}) {
  return { id: 't1', round_number: 1, trigger: 'pipeline', risk: 'critical', revised_risk: 'low', report: report(), applied_at: null, created_at: now, ...over }
}

const CAMPAIGN = {
  id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee for commuters', domain_category: 'food_beverage', feasibility_score: 40, feasibility_rationale: 'ok',
  status: 'awaiting_gate_2', current_round: 1, reddit_subreddit: null, email_to: null, cta_url: null, use_image_template: false,
  use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
  stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
}
const ITERATION = {
  id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1, copy_text: AD.body, headline: AD.headline, cta: AD.cta, image_prompt: 'coffee',
  preflight_score: 60, preflight_passed: true, bluesky_post_uri: null, reddit_post_url: null, email_id: null, image_style: 'minimalist', copy_tone: 'direct_factual', arm_index: 0, guardrail_flags: null,
}

async function signIn(page: Page, crash: object[] = [crashRow()]) {
  const sent: { capability: string; params: Record<string, unknown> }[] = []
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
    else if (url.includes('/campaigns?')) body = single ? CAMPAIGN : [CAMPAIGN]
    else if (url.includes('/iterations')) body = [ITERATION]
    else if (url.includes('/crash_tests')) body = crash
    else if (url.includes('/gate_decisions')) body = { id: 'g2', campaign_id: 'c1', gate_number: 2, round_number: 1, decision: null, decided_at: null }
    else if (url.includes('/capability_runs')) body = single ? { status: 'pending' } : []
    else if (url.includes('/gate_approvals') && method === 'POST') {
      votes.push(route.request().postDataJSON())
      body = null
    }
    await route.fulfill({ status: method === 'POST' ? 201 : 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  // Later routes win in Playwright: the catch-all first, the one we watch after it.
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/functions/v1/trigger-capability-run', async (route) => {
    sent.push(route.request().postDataJSON())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ run_id: 'run-1' }) })
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
  return { sent, votes }
}

test('Gate 2 shows the crash test: the marked ad, the findings and the revised version', async ({ page }) => {
  const { sent } = await signIn(page)
  await page.goto('/campaigns/c1')
  const report = page.getByTestId('crash-test')
  await expect(report.getByText('Critical risk').first()).toBeVisible()
  await expect(report.getByText(/simulation, not real customers/i)).toBeVisible()
  await expect(report.locator('mark').filter({ hasText: 'Rahul says' }).first()).toBeVisible()
  await expect(report.getByText('Invented testimonial or review').first()).toBeVisible()
  await expect(report.getByText('Price-sensitive buyer').first()).toBeVisible()
  await expect(report.getByText(/2 resolved/)).toBeVisible()
  await expect(report.getByText('Step off the metro and your coffee is waiting.', { exact: false }).first()).toBeVisible()

  await report.getByRole('button', { name: /use the revised version/i }).click()
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toEqual({ capability: 'apply_revision', params: { campaign_id: 'c1', round: 1, crash_test_id: 't1' } })
})

test('a critical crash test needs a reason to approve', async ({ page }) => {
  const { votes } = await signIn(page)
  await page.goto('/campaigns/c1')
  await expect(page.getByText(/found a critical problem/i).first()).toBeVisible()
  const approve = page.getByRole('button', { name: /^approve$/i })
  await expect(approve).toBeDisabled()
  await page.getByLabel(/why approve anyway/i).fill('Rahul is a real customer, consent on file')
  await expect(approve).toBeEnabled()
  await approve.click()
  await expect.poll(() => votes.length).toBe(1)
})

test('once the revision is applied its risk counts and no reason is needed', async ({ page }) => {
  await signIn(page, [crashRow({ applied_at: now })])
  await page.goto('/campaigns/c1')
  const report = page.getByTestId('crash-test')
  await expect(report.getByText(/revised version in use/i)).toBeVisible()
  await expect(report.getByText('Low risk').first()).toBeVisible()
  await expect(page.getByRole('button', { name: /^approve$/i })).toBeEnabled()
})

test('Tools: "Crash-test an ad" shows the report', async ({ page }) => {
  await signIn(page)
  await page.route('**/rest/v1/capability_runs?*', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify(/id=eq\./.test(route.request().url())
        ? { id: 'r1', capability: 'crash_test', status: 'completed', params: { idea: 'Coffee', copy: AD.body }, result: report(), error: null, created_at: now }
        : []),
    }),
  )
  await page.goto('/tools?run=r1')
  const result = page.getByTestId('crash-test')
  await expect(result.getByText('Critical risk').first()).toBeVisible()
  await expect(result.getByRole('button', { name: /use the revised version/i })).toHaveCount(0) // nothing to apply outside a campaign
})

test('the crash test fits a small phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 })
  await signIn(page)
  await page.goto('/campaigns/c1')
  await expect(page.getByTestId('crash-test')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})
