import { expect, test, type Page, type Route } from '@playwright/test'

// Finished ads against a mocked backend (same fake session as app.spec.ts):
// the stored ad at Gate 2, "New picture", and the brand-kit logo upload.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
// A 1x1 PNG: enough for <img> to fire onLoad.
const PIXEL = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64')

async function signIn(page: Page) {
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role: 'owner', organizations: ORG }]
    else if (url.includes('/rpc/')) body = null
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const now = Math.floor(Date.now() / 1000)
    localStorage.setItem(
      'sb-127-auth-token',
      JSON.stringify({
        access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: now + 3600,
        user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
      }),
    )
  }, USER)
}

/** Private-bucket images: POST .../object/sign/... hands out a signed URL, GET on it serves the picture. */
function serveSigned(page: Page, bucket: string, signed: string[]) {
  return page.route(`**/storage/v1/object/sign/${bucket}/**`, async (route: Route) => {
    const url = new URL(route.request().url())
    if (route.request().method() === 'POST') {
      signed.push(url.pathname)
      const path = url.pathname.split('/storage/v1')[1]
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ signedURL: `${path}?token=t${signed.length}` }) })
    }
    return route.fulfill({ status: 200, contentType: 'image/png', body: PIXEL })
  })
}

test('Gate 2 shows the finished ad, and "New picture" repaints it', async ({ page }) => {
  await signIn(page)
  const now = new Date().toISOString()
  const campaign = {
    id: 'c1', org_id: ORG.id, idea: 'Coffee pre-orders', domain_category: 'food_beverage', feasibility_score: 70, feasibility_rationale: 'ok',
    status: 'awaiting_gate_2', current_round: 1, reddit_subreddit: null, email_to: null, cta_url: null, use_image_template: false,
    use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
    stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
  }
  let version = 0
  const iteration = () => ({
    id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1, copy_text: 'Skip the queue.', image_prompt: 'a barista',
    image_path: 'c1/round-1.jpg', image_version: version, headline: 'Your coffee, ready', cta: 'Order ahead',
    preflight_score: 70, preflight_passed: true, bluesky_post_uri: null, reddit_post_url: null, email_id: null,
    image_style: 'lifestyle_aspirational', copy_tone: 'direct_factual', arm_index: 0, guardrail_flags: null,
  })
  await page.route('**/rest/v1/campaigns?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(campaign) }))
  await page.route('**/rest/v1/iterations?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([iteration()]) }))
  await page.route('**/rest/v1/gate_decisions?*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'g1', campaign_id: 'c1', gate_number: 2, round_number: 1, decision: null, decided_at: null }) }),
  )
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  // The re-drawn Pollinations preview must not be used when a stored ad exists.
  let previews = 0
  await page.route('**/image.pollinations.ai/**', (route) => {
    previews++
    return route.fulfill({ status: 200, contentType: 'image/png', body: PIXEL })
  })
  const signed: string[] = []
  await serveSigned(page, 'ad-images', signed)
  let invoked: Record<string, unknown> | null = null
  await page.route('**/functions/v1/trigger-capability-run', (route) => {
    invoked = route.request().postDataJSON()
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ run_id: 'r1' }) })
  })
  await page.route('**/rest/v1/capability_runs?*', (route) => {
    version = 1 // the worker repainted it
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'completed', error: null }) })
  })

  await page.goto('/campaigns/c1')
  const gate = page.locator('section').filter({ hasText: /gate 2/i }).first()
  // Storage calls queue behind the auth client's session lock: slow when the suite runs in parallel.
  await expect(gate.getByRole('heading', { name: 'The finished ad' })).toBeVisible({ timeout: 15_000 })
  // Its words, beside it (not drawn over the ad).
  await expect(gate.getByText('Your coffee, ready')).toBeVisible()
  await expect(gate.getByText('Order ahead')).toBeVisible()
  await expect(gate.getByRole('img', { name: 'a barista' })).toBeVisible({ timeout: 15_000 })
  expect(signed.some((p) => p.endsWith('/ad-images/c1/round-1.jpg'))).toBe(true)
  expect(previews).toBe(0)
  await expect(gate.getByText(/5 new pictures left/i)).toBeVisible()

  const before = signed.length
  await gate.getByRole('button', { name: /new picture/i }).click()
  expect(invoked).toEqual({ capability: 'ad_image', params: { campaign_id: 'c1', round: 1 } })
  await expect(page.getByText(/new picture ready/i)).toBeVisible({ timeout: 15_000 })
  await expect(gate.getByText(/4 new pictures left/i)).toBeVisible()
  // The new version is fetched again (a fresh signed URL), not served from the old one.
  expect(signed.length).toBeGreaterThan(before)
})

test('brand kit: upload a logo, see it, remove it', async ({ page }) => {
  await signIn(page)
  const uploads: string[] = []
  const removed: string[] = []
  const saved: Record<string, unknown>[] = []
  await page.route('**/storage/v1/object/brand-logos/**', (route) => {
    uploads.push(new URL(route.request().url()).pathname)
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ Key: 'k', Id: 'id' }) })
  })
  await page.route('**/storage/v1/object/brand-logos', (route) => {
    removed.push(String(route.request().postData()))
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await serveSigned(page, 'brand-logos', [])
  await page.route('**/rest/v1/brand_kits*', (route) => {
    if (route.request().method() === 'POST') saved.push(route.request().postDataJSON())
    return route.fulfill({ status: 200, contentType: 'application/json', body: route.request().method() === 'GET' ? 'null' : '[]' })
  })

  await page.goto('/settings#brand')
  const brand = page.locator('#brand')
  await expect(brand.getByText(/no logo yet/i)).toBeVisible({ timeout: 15_000 })
  await brand.getByLabel(/upload logo/i).setInputFiles({ name: 'logo.png', mimeType: 'image/png', buffer: PIXEL })
  await expect(page.getByText(/logo saved/i)).toBeVisible({ timeout: 15_000 })
  expect(uploads[0]).toMatch(new RegExp(`/brand-logos/${ORG.id}/logo-\\d+\\.png$`))
  expect(saved.at(-1)).toMatchObject({ org_id: ORG.id, logo_path: expect.stringMatching(/^.+\/logo-\d+\.png$/) })
  await expect(brand.getByRole('img', { name: /your brand logo/i })).toBeVisible()

  await brand.getByRole('button', { name: /^remove$/i }).click()
  await expect(page.getByText(/logo removed/i)).toBeVisible({ timeout: 15_000 })
  expect(saved.at(-1)).toMatchObject({ logo_path: null })
  expect(removed.join(' ')).toContain('logo-')
  await expect(brand.getByText(/no logo yet/i)).toBeVisible()
})

test('a logo that is not an image type is refused before upload', async ({ page }) => {
  await signIn(page)
  let uploaded = false
  await page.route('**/storage/v1/object/brand-logos/**', (route) => {
    uploaded = true
    return route.fulfill({ status: 200, body: '{}' })
  })
  await page.goto('/settings#brand')
  await page.locator('#brand').getByLabel(/upload logo/i).setInputFiles({ name: 'logo.gif', mimeType: 'image/gif', buffer: PIXEL })
  await expect(page.getByText(/png, jpeg or webp/i)).toBeVisible()
  expect(uploaded).toBe(false)
})
