import { expect, test, type Page, type Route } from '@playwright/test'

// App-wide toasts against a mocked backend (same fake-session approach as
// app.spec.ts). `fail` lists REST/function paths that should return a 500.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }

async function signIn(page: Page, fail: string[] = []) {
  const counts: Record<string, number> = {}
  const handle = async (route: Route) => {
    const url = route.request().url()
    const hit = fail.find((f) => url.includes(f))
    if (hit) {
      counts[hit] = (counts[hit] ?? 0) + 1
      return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ message: 'boom', error: 'boom' }) })
    }
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role: 'owner', organizations: ORG }]
    else if (url.includes('/rpc/org_usage')) body = { plan: 'free', limits: {}, used: {} }
    else if (url.includes('/rpc/')) body = null
    await route.fulfill({ status: route.request().method() === 'GET' ? 200 : 201, contentType: 'application/json', body: JSON.stringify(body) })
  }
  await page.route('**/rest/v1/**', handle)
  await page.route('**/functions/v1/**', handle)
  // The composer uploads the product photo before creating the campaign.
  await page.route('**/storage/v1/object/product-photos/**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ Key: 'product-photos/x.jpg' }) }),
  )
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
  return counts
}

const addPhoto = (page: Page) => page.getByTestId('product-photo-input').setInputFiles('e2e/fixtures/sample-ad.jpg')

// Each toast's role is alert/status (so screen readers announce it), not listitem.
const toasts = (page: Page) => page.getByRole('list', { name: /notifications/i }).locator('li')

test('a failed action shows an error toast that can be dismissed', async ({ page }) => {
  await signIn(page, ['/functions/v1/create-campaign'])
  await page.goto('/dashboard')
  await page.getByPlaceholder(/campaign idea/i).fill('Meal kits for night-shift nurses')
  await addPhoto(page)
  await page.getByRole('button', { name: /create campaign/i }).click()
  const toast = toasts(page).filter({ hasText: /couldn.t start the campaign/i })
  await expect(toast).toBeVisible()
  await expect(toast).toHaveAttribute('role', 'alert')

  // The same failure again refreshes the toast rather than stacking a copy.
  await page.getByRole('button', { name: /create campaign/i }).click()
  await expect(toasts(page).filter({ hasText: /couldn.t start the campaign/i })).toHaveCount(1)

  await toast.getByRole('button', { name: /dismiss/i }).click()
  await expect(toast).toHaveCount(0)
})

test('a successful save confirms with a success toast that clears itself', async ({ page }) => {
  await signIn(page)
  await page.goto('/settings')
  await page.getByRole('button', { name: /save brand kit/i }).click()
  const toast = toasts(page).filter({ hasText: /brand kit saved/i })
  await expect(toast).toBeVisible()
  await expect(toast).toHaveAttribute('role', 'status')
  await expect(toast).toHaveCount(0, { timeout: 8000 })
})

test('a failed page load says so and Retry loads again', async ({ page }) => {
  const counts = await signIn(page, ['/rest/v1/campaigns'])
  await page.goto('/dashboard')
  const toast = toasts(page).filter({ hasText: /couldn.t load/i })
  await expect(toast).toBeVisible()
  const before = counts['/rest/v1/campaigns']
  await toast.getByRole('button', { name: /retry/i }).click()
  await expect.poll(() => counts['/rest/v1/campaigns']).toBeGreaterThan(before)
})

test('toasts fit a small phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  await signIn(page, ['/functions/v1/create-campaign'])
  await page.goto('/dashboard')
  await page.getByPlaceholder(/campaign idea/i).fill('x')
  await addPhoto(page)
  await page.getByRole('button', { name: /create campaign/i }).click()
  await expect(toasts(page).first()).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('a slow page load is covered by the blurred loader until the data arrives', async ({ page }) => {
  await signIn(page)
  // Hold the campaigns request back so the loader has time to show.
  await page.route('**/rest/v1/campaigns?*', async (route) => {
    await new Promise((r) => setTimeout(r, 1500))
    await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
  })
  await page.goto('/dashboard')
  const loader = page.getByRole('status', { name: /loading/i })
  await expect(loader).toBeVisible()
  const blur = await page.locator('[data-page-loader]').evaluate((el) => getComputedStyle(el).backdropFilter)
  expect(blur).toContain('blur')
  await expect(loader).toBeHidden({ timeout: 6000 })
  await expect(page.getByRole('heading', { name: /good (morning|afternoon|evening)/i })).toBeVisible()
})

test('a failed load drops the loader so the Retry toast is usable', async ({ page }) => {
  await signIn(page, ['/rest/v1/campaigns'])
  await page.goto('/campaigns/c1')
  await expect(toasts(page).filter({ hasText: /couldn.t load/i })).toBeVisible()
  await expect(page.getByRole('status', { name: /loading/i })).toBeHidden()
})
