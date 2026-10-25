import { expect, test, type Page } from '@playwright/test'

// The composer's product fields: the photo is required, uploaded into the
// user's own folder first, then sent to create-campaign with the tagline and link.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }

async function signIn(page: Page) {
  const seen: { uploads: string[]; created: Record<string, unknown>[] } = { uploads: [], created: [] }
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role: 'owner', organizations: ORG }]
    else if (url.includes('/rpc/org_usage')) body = { plan: 'free', limits: {}, used: {} }
    else if (url.includes('/rpc/')) body = null
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/storage/v1/object/product-photos/**', async (route) => {
    seen.uploads.push(new URL(route.request().url()).pathname.split('/product-photos/')[1])
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ Key: 'ok' }) })
  })
  await page.route('**/functions/v1/create-campaign', async (route) => {
    if (route.request().method() === 'POST') seen.created.push(route.request().postDataJSON())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dispatched: true }) })
  })
  await page.route('**/functions/v1/trigger-capability-run', async (route) => {
    if (route.request().method() === 'POST') seen.created.push(route.request().postDataJSON())
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ run_id: 'run-1' }) })
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
  return seen
}

test('a campaign needs a product photo, which is uploaded before the campaign starts', async ({ page }) => {
  const seen = await signIn(page)
  await page.goto('/dashboard')
  await page.getByPlaceholder(/campaign idea/i).fill('Order-ahead coffee for metro commuters')
  const start = page.getByRole('button', { name: /create campaign/i })
  await expect(start).toBeDisabled()

  await page.getByTestId('product-photo-input').setInputFiles('e2e/fixtures/sample-ad.jpg')
  await expect(page.getByTestId('product-photo').locator('img')).toBeVisible()
  await page.getByLabel(/tagline/i).fill('Coffee that waits for you')
  await page.getByLabel(/^link/i).fill('https://brewline.example/order')
  await expect(start).toBeEnabled()
  await start.click()

  await expect.poll(() => seen.created.length).toBe(1)
  expect(seen.uploads[0]).toMatch(new RegExp(`^${USER.id}/[0-9a-f-]{36}\.jpg$`))
  expect(seen.created[0]).toMatchObject({
    product_image_path: seen.uploads[0], tagline: 'Coffee that waits for you', cta_url: 'https://brewline.example/order',
  })
  // The composer is ready for the next campaign.
  await expect(page.getByTestId('product-photo').locator('img')).toHaveCount(0)
})

test('a link that is not a web address is flagged and blocks the start', async ({ page }) => {
  await signIn(page)
  await page.goto('/dashboard')
  await page.getByPlaceholder(/campaign idea/i).fill('Order-ahead coffee')
  await page.getByTestId('product-photo-input').setInputFiles('e2e/fixtures/sample-ad.jpg')
  await page.getByLabel(/^link/i).fill('brewline dot com')
  await expect(page.getByText(/web address starting with https/i)).toBeVisible()
  await expect(page.getByRole('button', { name: /create campaign/i })).toBeDisabled()
})

test('the product row fits a small phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 640 })
  await signIn(page)
  await page.goto('/dashboard')
  await expect(page.getByTestId('product-photo')).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('the ad image tool also builds on a product photo, with an optional template', async ({ page }) => {
  const seen = await signIn(page)
  await page.goto('/tools')
  await page.getByRole('radio', { name: /ad image/i }).click()
  await page.getByPlaceholder(/canvas sneakers/i).fill('Canvas sneakers for all-day comfort')
  const run = page.getByRole('button', { name: /^run/i })
  await expect(run).toBeDisabled()

  await page.getByTestId('product-photo-input').setInputFiles('e2e/fixtures/sample-ad.jpg')
  await page.getByLabel(/tagline/i).fill('Made to move')
  await page.getByRole('combobox', { name: /template/i }).click()
  await page.getByRole('option', { name: /type sandwich/i }).click()
  await run.click()

  await expect.poll(() => seen.created.length).toBe(1)
  const body = seen.created[0] as { capability: string; params: Record<string, string> }
  expect(body.capability).toBe('image')
  expect(body.params).toMatchObject({ prompt: 'Canvas sneakers for all-day comfort', tagline: 'Made to move', template: 'type_sandwich', product_image_path: seen.uploads[0] })
})
