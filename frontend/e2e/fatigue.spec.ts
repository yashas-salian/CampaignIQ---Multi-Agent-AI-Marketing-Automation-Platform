import { expect, test, type Page } from '@playwright/test'

// Creative fatigue on the campaign page, against a mocked backend: the verdict
// and its evidence per segment (rates per round, baseline, drop and interval,
// similarity, comparators), a social channel shown but never judged, the
// proposed refresh and the people's choice (refresh or keep), refreshes with
// their measured outcome, near-duplicates kept apart, roles, and phones.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()

const CAMPAIGN = {
  id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee for commuters', domain_category: 'food_beverage', feasibility_score: 60, feasibility_rationale: 'ok',
  status: 'awaiting_next_round', current_round: 6, reddit_subreddit: null, email_to: ['a@x.io'], cta_url: null, use_image_template: false,
  use_email_template: false, max_rounds: 8, max_duration_minutes: null, campaign_summary: null, distributed_at: now,
  stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
}
// A real verdict from src/capabilities/fatigue.py (a worn-out email concept) plus a social channel.
const RESULT = {"policy_version": "fatigue-v1", "analyzed_at": "2026-10-26T09:00:00+00:00", "segments": [{"periods": [{"round": 1, "exposures": 800, "successes": 50, "stale": false, "unique": true}, {"round": 2, "exposures": 800, "successes": 48, "stale": false, "unique": true}, {"round": 3, "exposures": 800, "successes": 35, "stale": false, "unique": true}, {"round": 4, "exposures": 800, "successes": 28, "stale": false, "unique": true}, {"round": 5, "exposures": 800, "successes": 24, "stale": false, "unique": true}], "status": "FATIGUE_CONFIRMED", "reason": "SIGNIFICANT_SUSTAINED_DROP", "recommendation": "TEST_REFRESH", "baseline": {"rounds": [1, 2], "rate": 0.0612, "interval": [0.0505, 0.0741]}, "recent": {"rounds": [4, 5], "rate": 0.0325, "interval": [0.0249, 0.0424]}, "relative_drop": 0.4694, "interval": [-0.0437, -0.0142], "sustained": true, "similarity_to_fresh": 0.82, "comparators": [0.05, 0.06], "min_exposures": 100, "min_periods": 3, "channel": "email", "segment": "a", "similarity": {"copy": 0.94, "visual": 1.0, "hook": 0.57, "cta": 1.0, "total": 0.82}, "comparator_drops": {"other_variant": 0.05, "organisation_email": 0.06}, "suggested_strategy": "NEW_HOOK", "strategy_record": {"NEW_HOOK": {"improved": 2, "tried": 3, "posterior_mean": 0.6}, "NEW_VISUAL": {"improved": 1, "tried": 2, "posterior_mean": 0.5}, "NEW_ANGLE": {"improved": 0, "tried": 0, "posterior_mean": 0.5}, "NEW_OFFER_FRAMING": {"improved": 0, "tried": 0, "posterior_mean": 0.5}}}, {"periods": [{"round": 1, "exposures": null, "successes": null, "stale": false, "engagement": 14}, {"round": 2, "exposures": null, "successes": null, "stale": false, "engagement": 11}, {"round": 3, "exposures": null, "successes": null, "stale": false, "engagement": 9}, {"round": 4, "exposures": null, "successes": null, "stale": false, "engagement": 7}, {"round": 5, "exposures": null, "successes": null, "stale": false, "engagement": 6}], "status": "NOT_MEASURABLE", "reason": "NO_EXPOSURE_DATA", "recommendation": "KEEP", "baseline": null, "recent": null, "relative_drop": null, "interval": null, "sustained": null, "similarity_to_fresh": null, "comparators": [], "min_exposures": 100, "min_periods": 3, "channel": "bluesky", "segment": "all"}], "duplicates": [{"round": 2, "of_round": 1, "similarity": {"total": 0.93}}, {"round": 4, "of_round": 1, "similarity": {"total": 0.9}}]}
const REPORT = { campaign_id: 'c1', policy_version: 'fatigue-v1', analyzed_at: now, result: RESULT }
const ALERT = { id: 'al1', channel: 'email', segment: 'a', status: 'FATIGUE_CONFIRMED', recommendation: 'TEST_REFRESH', state: 'refreshing', note: null, created_at: now }
const PENDING = { id: 'iv2', alert_id: 'al1', channel: 'email', segment: 'a', strategy: 'NEW_HOOK', requested_by: null, applied_round: null,
  outcome: 'pending', outcome_detail: null, created_at: now }
const DONE = { id: 'iv1', alert_id: 'al0', channel: 'email', segment: 'a', strategy: 'NEW_VISUAL', requested_by: null, applied_round: 3,
  outcome: 'IMPROVED', outcome_detail: { rate_before: 0.0325, rate_after: 0.055, change: 0.0225, interval: [0.0056, 0.0421], design: 'sequential' }, created_at: now }

async function signIn(page: Page, role = 'owner', alerts: object[] = [ALERT], interventions: object[] = [PENDING, DONE]) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc) {
      if (['request_creative_refresh', 'dismiss_fatigue_alert'].includes(rpc)) rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = null
    } else if (url.includes('/campaigns?')) body = single ? CAMPAIGN : [CAMPAIGN]
    else if (url.includes('/creative_fatigue_reports')) body = REPORT
    else if (url.includes('/creative_fatigue_alerts')) body = alerts
    else if (url.includes('/creative_interventions')) body = interventions
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
  await expect(page.getByTestId('creative-fatigue')).toBeVisible({ timeout: 15_000 })
}

test('the verdict comes with its evidence: rates per round, the drop and its interval, similarity, comparisons', async ({ page }) => {
  await signIn(page)
  await open(page)
  const email = page.getByTestId('fatigue-email-a')
  await expect(email.getByText('Email, variant A: fatigue confirmed')).toBeVisible()
  await expect(email.getByText('Test a refresh')).toBeVisible()
  await expect(email.getByText(/whole 95% range of the drop is below zero/)).toBeVisible()
  await expect(email.getByRole('button', { name: /^Round 5: 3\.0% \(24 of 800; 95%:/ })).toBeVisible()
  await expect(email.getByText('Fresh (round 1, 2)')).toBeVisible()
  await expect(email.getByText('Recent ads are 82% like the fresh ones:')).toBeVisible()
  await expect(email.getByText(/Other variant dropped 5%/)).toBeVisible()
})

test('a social channel is shown but never called fatigued', async ({ page }) => {
  await signIn(page)
  await open(page)
  const social = page.getByTestId('fatigue-bluesky-all')
  await expect(social.getByText("Bluesky: can't be measured")).toBeVisible()
  await expect(social.getByText(/doesn't report how many people saw the post/)).toBeVisible()
  await expect(social.getByText(/Round 1: 14/)).toBeVisible()
})

test('the proposed refresh can be changed, or the creative kept', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await open(page)
  const action = page.getByTestId('fatigue-action')
  await expect(action.getByText(/Next round will try a refresh: a new opening line \(suggested\)/)).toBeVisible()
  await expect(action.getByText(/still goes through the checks, the crash test and Gate 2/)).toBeVisible()
  await action.getByRole('combobox', { name: 'Refresh by' }).click()
  await page.getByRole('option', { name: 'a new visual' }).click()
  await action.getByRole('button', { name: 'Use this refresh' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'request_creative_refresh')?.args).toEqual({ p_alert: 'al1', p_strategy: 'NEW_VISUAL' })
  await action.getByLabel('Why keep it? (optional)').fill('Seasonal dip, it will recover')
  await action.getByRole('button', { name: 'Keep the creative' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'dismiss_fatigue_alert')?.args).toEqual({ p_alert: 'al1', p_note: 'Seasonal dip, it will recover' })
})

test('refreshes show their measured outcome, and duplicates are kept apart from fatigue', async ({ page }) => {
  await signIn(page)
  await open(page)
  const panel = page.getByTestId('creative-fatigue')
  await expect(panel.getByText('Refreshes tried')).toBeVisible()
  await expect(panel.getByText('3.3% before, 5.5% after (change 95%: +0.6 to +4.2 pts)')).toBeVisible()
  await expect(panel.getByText(/a before\/after comparison/)).toBeVisible()
  await expect(panel.getByText('Near-duplicates')).toBeVisible()
  await expect(panel.getByText('Round 2 is 93% like round 1')).toBeVisible()
  await expect(panel.getByText(/a near-duplicate can still work/)).toBeVisible()
  await expect(panel.getByText(/What has worked here before:/)).toBeVisible()
})

test('viewers see the verdict but cannot refresh or keep', async ({ page }) => {
  await signIn(page, 'viewer')
  await open(page)
  await expect(page.getByTestId('fatigue-action')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Use this refresh' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Keep the creative' })).toHaveCount(0)
})

// Review screenshots: CF_SHOTS=<dir> npx playwright test e2e/fatigue.spec.ts -g screenshots
test('screenshots of the creative fatigue panel', async ({ page }, info) => {
  const dir = process.env.CF_SHOTS
  test.skip(!dir, 'set CF_SHOTS to a folder to capture them')
  await signIn(page)
  await open(page)
  await page.getByTestId('creative-fatigue').screenshot({ path: `${dir}/fatigue-${info.project.name}.png` })
})

test('the panel fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page)
  await open(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
