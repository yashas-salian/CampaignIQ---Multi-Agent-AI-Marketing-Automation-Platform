import { expect, test, type Page } from '@playwright/test'

// Proof of impact in the UI, against a mocked backend: pre-registering the
// experiment (with its sample-size plan), the declared design and withdrawing
// it, the impact report (verdict, causal estimate apart from observed counts and
// attribution, data quality), interim numbers without a verdict, and phones.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()
const EMAILS = Array.from({ length: 40 }, (_, i) => `commuter${i}@example.test`)
// The sample-size plan needs a realistic list; the other tests keep the mocked payload small.
const BIG_LIST = Array.from({ length: 3000 }, (_, i) => `commuter${i}@example.test`)

const CAMPAIGN = {
  id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee for commuters', domain_category: 'food_beverage', feasibility_score: 60, feasibility_rationale: 'ok',
  status: 'awaiting_gate_2', current_round: 1, reddit_subreddit: null, email_to: EMAILS, cta_url: 'https://brew.example', use_image_template: false,
  use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
  stop_requested: false, target_language: 'en', created_at: now, updated_at: now, ab_test: false,
}
// A real engine result (src/capabilities/impact.py analyze_counts: 18/600 vs 132/2400), with revenue added.
const RESULT = { ...{"policy_version": "impact-v1", "status": "POSITIVE_IMPACT", "reason": "INTERVAL_ABOVE_ZERO", "final": true, "interim": false, "primary_metric": "conversion_rate", "design": "holdout", "min_effect": 0.01, "practically_significant": true, "window": {"started_at": "2026-01-01T00:00:00+00:00", "ends_at": "2026-01-15T00:00:00+00:00", "analysis_at": "2026-01-22T00:00:00+00:00", "attribution_window_days": 7}, "arms": {"control": {"units": 600, "exposed": 0, "clickers": 0, "converters": 18, "qualified": 18, "successes": 18, "rate": 0.03, "rate_interval": [0.0191, 0.0469], "revenue": 0.0, "revenue_per_unit": 0.0}, "treatment": {"units": 2400, "exposed": 2390, "clickers": 310, "converters": 132, "qualified": 132, "successes": 132, "rate": 0.055, "rate_interval": [0.0466, 0.0649], "revenue": 0.0, "revenue_per_unit": 0.0}}, "estimate": {"treatment_arms": ["treatment"], "control_arms": ["control"], "treatment_units": 2400, "control_units": 600, "treatment_successes": 132, "control_successes": 18, "treatment_rate": 0.055, "control_rate": 0.03, "absolute_lift": 0.025, "interval": [0.0061, 0.0397], "prob_treatment_better": 0.9947, "relative_lift": 0.7821, "relative_interval": [0.1383, 1.943], "relative_note": null, "incremental_successes": 60.0, "incremental_interval": [14.6, 95.3], "causal": true}, "secondary": null, "revenue": {"currency": "USD", "mixed_currencies": false, "incremental_revenue": 1500.0, "incremental_interval": [420.0, 2580.0], "average_conversion_value": 25.0, "attributed_revenue": 2650.0, "attribution_model": "a click before converting, within 7 days (not causal)"}, "quality": {"srm_p_value": 1.0, "sample_ratio_mismatch": false, "expected_shares": {"control": 0.2, "treatment": 0.8}, "min_units_per_arm": 500, "smallest_group": 600, "conversions_received": 150, "unmatched_conversions": 0, "last_exposure_at": null, "last_click_at": null, "last_conversion_at": null, "stale_outcomes": false, "no_conversions_yet": false}, "assumptions": ["INTENTION_TO_TREAT", "OUTCOME_WINDOW_FIXED", "CONTROL_SEES_OTHER_CHANNELS", "CONVERSIONS_MATCHED_BY_TOKEN_OR_EMAIL"], "recommended_action": "KEEP_AND_EXTEND", "analyzed_at": "2026-01-23T00:00:00+00:00", "bandit": {"fed": true}}, analyzed_at: now }
RESULT.quality = { ...RESULT.quality, last_conversion_at: new Date(Date.now() - 5 * 3600_000).toISOString() }
const EXPERIMENT = {
  id: 'e1', campaign_id: 'c1', hypothesis: 'Emailing commuters raises sign-ups', primary_metric: 'conversion_rate', design: 'holdout',
  control_share: 0.2, attribution_window_days: 7, duration_days: 14, min_units_per_arm: 500, min_effect: 0.01, baseline_rate: 0.03,
  policy_version: 'impact-v1', status: 'completed', started_at: '2026-01-01T00:00:00Z', ends_at: '2026-01-15T00:00:00Z',
  analysis_at: '2026-01-22T00:00:00Z', result: RESULT, result_status: 'POSITIVE_IMPACT', analyzed_at: now, concluded_at: now,
}

async function signIn(page: Page, opts: { role?: string; campaign?: object; experiment?: object | null } = {}) {
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
      if (['declare_experiment', 'withdraw_experiment'].includes(rpc)) rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = rpc === 'declare_experiment' ? 'e1' : null
    } else if (url.includes('/campaigns?')) body = single ? campaign : [campaign]
    else if (url.includes('/experiments')) body = opts.experiment === undefined ? null : opts.experiment
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

// The first load can be slow while six browsers start at once (the repo's usual 15 s allowance).
async function open(page: Page) {
  await page.goto('/campaigns/c1')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 15_000 })
}

test('pre-register an experiment before the first send, with its sample-size plan', async ({ page }) => {
  const { rpcs } = await signIn(page, { campaign: { ...CAMPAIGN, email_to: BIG_LIST } })
  await open(page)
  const panel = page.getByTestId('proof-of-impact')
  await expect(panel.getByText(/3,000 email recipients/)).toBeVisible()
  await panel.getByRole('button', { name: 'Set up the experiment' }).click()
  const declare = panel.getByRole('button', { name: 'Pre-register' })
  await expect(declare).toBeDisabled()
  await panel.getByLabel('Hypothesis').fill('Emailing commuters raises qualified sign-ups')
  // 20% of 3,000 = 600 held out; a 1-point lift on 3% needs about 5,300 per group: too few, and it says so.
  await expect(panel.getByTestId('impact-plan')).toContainText('about 600')
  await expect(panel.getByTestId('impact-plan')).toContainText('inconclusive')
  await panel.getByLabel('Smallest lift worth acting on (points)').fill('5')
  await expect(panel.getByTestId('impact-plan')).not.toContainText('inconclusive')
  await declare.click()
  await expect.poll(() => rpcs.length).toBe(1)
  expect(rpcs[0].name).toBe('declare_experiment')
  expect(rpcs[0].args).toMatchObject({ p_campaign: 'c1', p_hypothesis: 'Emailing commuters raises qualified sign-ups',
    p_metric: 'qualified_signup_rate', p_control_share: 0.2, p_window_days: 7, p_duration_days: 14, p_min_effect: 0.05 })
})

test('a declared experiment shows its design and can be withdrawn before it starts', async ({ page }) => {
  const { rpcs } = await signIn(page, { experiment: { ...EXPERIMENT, status: 'declared', started_at: null, result: null } })
  await open(page)
  const panel = page.getByTestId('proof-of-impact')
  await expect(panel.getByText('Pre-registered')).toBeVisible()
  await expect(panel.getByText('Emailing commuters raises sign-ups')).toBeVisible()
  await expect(panel.getByText(/Fixed: 14 days of sending plus a 7-day window/)).toBeVisible()
  await panel.getByRole('button', { name: 'Withdraw' }).click()
  await expect.poll(() => rpcs[0]?.name).toBe('withdraw_experiment')
})

test('the impact report keeps the causal estimate, the observed counts and attribution apart', async ({ page }) => {
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'completed' }, experiment: EXPERIMENT })
  await open(page)
  const panel = page.getByTestId('proof-of-impact')
  await expect(panel.getByText('The campaign caused more sign-ups')).toBeVisible()
  await expect(panel.getByText('The whole 95% interval of the lift is above zero.')).toBeVisible()
  await expect(panel.getByText('Design locked')).toBeVisible()
  await expect(panel.getByText('causal: randomized').first()).toBeVisible()
  await expect(panel.getByRole('button', { name: /Campaign vs control: \+2\.5 pts \(95%:/ })).toBeVisible()
  await expect(panel.getByRole('row', { name: /Control \(not emailed\)/ })).toContainText('600')
  await expect(panel.getByText('attribution, not causal')).toBeVisible()
  await expect(panel.getByText('Group sizes match the planned split.')).toBeVisible()
  await expect(panel.getByText('The learning model was updated with these conversions.')).toBeVisible()
})

test('interim numbers carry no verdict', async ({ page }) => {
  const interim = { ...RESULT, status: 'COLLECTING', reason: 'BEFORE_PREDECLARED_END', final: false, interim: true,
    window: { ...RESULT.window, analysis_at: '2026-11-15T00:00:00Z' } }
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'awaiting_metrics' }, experiment: { ...EXPERIMENT, status: 'running', result: interim } })
  await open(page)
  const panel = page.getByTestId('proof-of-impact')
  await expect(panel.getByText('Collecting data')).toBeVisible()
  await expect(panel.getByText('Interim', { exact: true })).toBeVisible()
  await expect(panel.getByText(/The verdict comes at the predeclared end/)).toBeVisible()
})

test('no conversions reported is inconclusive, not no effect', async ({ page }) => {
  const none = { ...RESULT, status: 'INCONCLUSIVE', reason: 'NO_OUTCOME_DATA', revenue: null }
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'completed' }, experiment: { ...EXPERIMENT, result: none } })
  await open(page)
  const panel = page.getByTestId('proof-of-impact')
  await expect(panel.getByText('Inconclusive: no claim either way')).toBeVisible()
  await expect(panel.getByText(/Check the conversion integration/)).toBeVisible()
})

test('viewers see no setup', async ({ page }) => {
  await signIn(page, { role: 'viewer' })
  await open(page)
  await expect(page.getByTestId('proof-of-impact')).toHaveCount(0)
})

// Review screenshots: IMPACT_SHOTS=<dir> npx playwright test e2e/impact.spec.ts -g screenshots
test('screenshots of the impact report and the setup form', async ({ page }, info) => {
  const dir = process.env.IMPACT_SHOTS
  test.skip(!dir, 'set IMPACT_SHOTS to a folder to capture them')
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'completed' }, experiment: EXPERIMENT })
  await open(page)
  await page.getByTestId('proof-of-impact').screenshot({ path: `${dir}/impact-report-${info.project.name}.png` })
})

test('the impact report fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page, { campaign: { ...CAMPAIGN, status: 'completed' }, experiment: EXPERIMENT })
  await open(page)
  await expect(page.getByTestId('proof-of-impact')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
