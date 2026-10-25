import { expect, test, type Page } from '@playwright/test'

// Competitor intelligence in the UI, against a mocked backend: the timeline of
// observed moves (sources, times, several reports counted once), the insight
// with all four options and the inferred intent kept apart, the forecast,
// sources that need approval, a stale source flagged, and roles.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const hoursAgo = (h: number) => new Date(Date.now() - h * 3600_000).toISOString()

const SOURCES = [
  { id: 's1', kind: 'webpage', locator: 'https://brewco.example/pricing', approved: true, status: 'ok', last_fetched_at: hoursAgo(2), last_ok_at: hoursAgo(2), last_error: null },
  { id: 's2', kind: 'news', locator: 'BrewCo', approved: true, status: 'stale', last_fetched_at: hoursAgo(1), last_ok_at: hoursAgo(100), last_error: 'HTTPError: 429' },
  { id: 's3', kind: 'rss', locator: 'https://brewco.example/feed', approved: false, status: 'never', last_fetched_at: null, last_ok_at: null, last_error: null },
]
const COMPETITOR = { id: 'k1', org_id: ORG.id, name: 'BrewCo', website: 'https://brewco.example/pricing', keywords: ['BrewCo'],
  category_keyword: 'cold brew coffee', markets: ['US'], created_at: hoursAgo(300), competitor_sources: SOURCES }
const EVENTS = [
  { id: 'e1', kind: 'OFFER_CHANGE', summary: 'New offer on brewco.example: “Get 40% off your first month.”',
    observed: { change: 'added', after: 'Get 40% off your first month.' }, url: 'https://brewco.example/pricing', outlet: 'brewco.example',
    published_at: null, observed_at: hoursAgo(5), reports: 1, outlets: ['brewco.example'], original_outlet: 'brewco.example', confidence: 0.9 },
  { id: 'e2', kind: 'PRODUCT_LAUNCH', summary: 'BrewCo launches cold brew subscription for commuters',
    observed: { headline: 'BrewCo launches cold brew subscription for commuters' }, url: 'https://news.example/a', outlet: 'Reuters',
    published_at: hoursAgo(30), observed_at: hoursAgo(28), reports: 3, outlets: ['Reuters', 'Yahoo', 'MarketWatch'], original_outlet: 'Reuters', confidence: 0.6 },
]
const OPTIONS = (pick: string, reason: string) => ['RESPOND', 'MONITOR', 'DIFFERENTIATE', 'NO_ACTION'].map((a) => ({
  action: a, recommended: a === pick, reasons: [a === pick ? reason : { RESPOND: 'RESPOND_COSTS', MONITOR: 'MONITOR_WAITS', DIFFERENTIATE: 'DIFFERENTIATE_NEEDS_ANGLE', NO_ACTION: 'NO_ACTION_RISK' }[a]],
}))
const INSIGHTS = [
  { id: 'i1', event_id: 'e1', recommendation: 'RESPOND', options: OPTIONS('RESPOND', 'DEEP_OFFER_ON_YOUR_MARKET'), confidence: 0.9, status: 'open', note: null,
    relevance: { relevant: true, live_campaigns: [{ id: 'c1', idea: 'Order-ahead cold brew coffee' }] },
    explanations: [{ hypothesis: 'Clearing summer stock before autumn', would_confirm: 'The offer ends in September', would_refute: 'It runs all year', inferred: true, source: 'llm' },
                   { hypothesis_code: 'ACQUISITION_PUSH', inferred: true, source: 'template' }] },
  { id: 'i2', event_id: 'e2', recommendation: 'MONITOR', options: OPTIONS('MONITOR', 'UNCONFIRMED'), confidence: 0.6, status: 'open', note: null,
    relevance: { relevant: true, live_campaigns: [] }, explanations: [{ hypothesis_code: 'CATEGORY_EXPANSION', inferred: true, source: 'template' }] },
]
const PREDICTIONS = [
  { id: 'p1', event_id: 'e1', keyword: 'cold brew coffee', horizon_days: 14, origin_week: '2026-10-18', predicted_change: 0.031,
    interval_low: -0.12, interval_high: 0.15, interval_level: 0.8, model_version: 'trend-v1', status: 'pending', observed_change: null,
    inside_interval: null, materialized: null, resolve_after: '2026-11-10T00:00:00Z' },
  { id: 'p0', event_id: 'e2', keyword: 'cold brew coffee', horizon_days: 14, origin_week: '2026-09-20', predicted_change: 0.12,
    interval_low: 0.01, interval_high: 0.22, interval_level: 0.8, model_version: 'trend-v1', status: 'resolved', observed_change: 0.17,
    inside_interval: true, materialized: true, resolve_after: '2026-10-13T00:00:00Z' },
]

async function signIn(page: Page, role = 'owner', competitors: object[] = [COMPETITOR]) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc) {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = rpc === 'upsert_competitor' ? 'k2' : null
    } else if (url.includes('/competitors?')) body = competitors
    else if (url.includes('/competitor_events')) body = EVENTS
    else if (url.includes('/competitor_insights')) body = INSIGHTS
    else if (url.includes('/competitor_predictions')) body = PREDICTIONS
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{"run_id":"r1"}' }))
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
  await page.goto('/competitors')
  await expect(page.getByRole('heading', { level: 1, name: 'Competitors' })).toBeVisible({ timeout: 15_000 })
}

test('the timeline shows observed moves with their source, and one story once', async ({ page }) => {
  await signIn(page)
  await open(page)
  const timeline = page.getByTestId('ci-timeline')
  await expect(timeline.getByRole('heading', { name: 'What BrewCo did' })).toBeVisible()
  await expect(timeline.getByText('Offer change')).toBeVisible()
  await expect(timeline.getByText('After:')).toBeVisible()
  await expect(timeline.getByText('observed', { exact: true }).first()).toBeVisible()
  await expect(timeline.getByText('3 reports of one story: Reuters, Yahoo, MarketWatch')).toBeVisible()
  await expect(timeline.getByRole('link', { name: 'Reuters' })).toHaveAttribute('href', 'https://news.example/a')
})

test('an insight weighs all four options and keeps inferred intent apart', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await open(page)
  const event = page.getByTestId('ci-timeline').getByRole('listitem').filter({ hasText: '40% off' }).first()
  await expect(event.getByText('Respond').first()).toBeVisible()
  for (const option of ['Monitor', 'Differentiate', 'No action']) await expect(event.getByText(option, { exact: true })).toBeVisible()
  await expect(event.getByText(/buyers will weigh it against yours/)).toBeVisible()
  await expect(event.getByText('Affects: “Order-ahead cold brew coffee”')).toBeVisible()
  await event.getByText('Why might they have done it?').click()
  await expect(event.getByText('inferred, not observed')).toBeVisible()
  await expect(event.getByText('Clearing summer stock before autumn')).toBeVisible()
  await expect(event.getByText('A push for new customers.')).toBeVisible()
  await event.getByLabel('Note').fill('Ran a value-for-money ad')
  await event.getByRole('button', { name: 'Mark acted on' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'decide_competitor_insight')?.args).toEqual(
    { p_insight: 'i1', p_status: 'acted', p_note: 'Ran a value-for-money ad' })
})

test('forecasts show their range, and a checked one shows what happened', async ({ page }) => {
  await signIn(page)
  await open(page)
  const forecasts = page.getByTestId('ci-forecast')
  await expect(forecasts.first()).toContainText('+3.1%')
  await expect(forecasts.first()).toContainText('80% range: −12% to +15%')
  await expect(forecasts.nth(1)).toContainText('Observed: +17.0%. Inside the range. The rise happened.')
  await expect(page.getByTestId('ci-forecast-record')).toContainText('1,198 held-out past forecasts')
  await expect(page.getByTestId('ci-forecast-record')).toContainText('1 forecast checked, 1 inside its range')
})

test('stale sources are flagged, and nothing is fetched until a source is approved', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await open(page)
  await expect(page.getByTestId('ci-limitations')).toContainText('News: stale')
  const sources = page.getByTestId('ci-sources')
  await expect(sources.getByText('waiting for approval')).toBeVisible()
  await sources.getByRole('listitem').filter({ hasText: 'brewco.example/feed' }).getByRole('button', { name: 'Approve' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'approve_competitor_source')?.args).toEqual({ p_source: 's3', p_approved: true })
})

test('adding a competitor proposes its page and news as sources, unapproved', async ({ page }) => {
  const { rpcs } = await signIn(page, 'owner', [])
  await open(page)
  await expect(page.getByText('No competitors yet.')).toBeVisible()
  const form = page.getByTestId('add-competitor')
  await form.getByLabel('Name', { exact: true }).fill('MealBox')
  await form.getByLabel('Page to watch (optional)').fill('https://mealbox.example')
  await form.getByLabel('Their market, as people search it (optional)').fill('meal kit')
  await form.getByRole('button', { name: 'Add competitor' }).click()
  await expect.poll(() => rpcs.filter((r) => r.name === 'add_competitor_source').length).toBe(2)
  expect(rpcs.find((r) => r.name === 'upsert_competitor')?.args).toMatchObject({ p_name: 'MealBox', p_category_keyword: 'meal kit' })
  expect(rpcs.filter((r) => r.name === 'add_competitor_source').every((r) => r.args.p_approve === false)).toBe(true)
})

test('viewers read but cannot change the watch list', async ({ page }) => {
  await signIn(page, 'viewer')
  await open(page)
  await expect(page.getByTestId('ci-timeline')).toBeVisible()
  await expect(page.getByTestId('add-competitor')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Mark acted on' })).toHaveCount(0)
})

// Review screenshots: CI_SHOTS=<dir> npx playwright test e2e/competitors.spec.ts -g screenshots
test('screenshots of the competitors page', async ({ page }, info) => {
  const dir = process.env.CI_SHOTS
  test.skip(!dir, 'set CI_SHOTS to a folder to capture them')
  await signIn(page)
  await open(page)
  await page.getByText('Why might they have done it?').first().click()
  await page.screenshot({ path: `${dir}/competitors-${info.project.name}.png`, fullPage: true })
})

test('the competitors page fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page)
  await open(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
