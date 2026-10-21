import { expect, test, type Page } from '@playwright/test'

// Signed-in pages against a mocked backend: a fake session in localStorage
// (supabase-js trusts an unexpired stored session without a network call) and
// canned PostgREST / RPC answers. Nothing reaches a real Supabase project.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }

async function signIn(page: Page) {
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role: 'owner', organizations: ORG }]
    else if (url.includes('/rpc/org_usage'))
      body = {
        plan: 'free',
        limits: { campaigns_per_day: 3, active_campaigns: 3, members: 5, llm_tokens_per_day: 150000 },
        used: { campaigns_per_day: 1, active_campaigns: 1, members: 1, llm_tokens_per_day: 30000 },
      }
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

test('dashboard renders for a signed-in user with plan usage', async ({ page }) => {
  await signIn(page)
  await page.goto('/dashboard')
  await expect(page.getByRole('progressbar').first()).toBeVisible()
  await expect(page.getByText('1 / 3').first()).toBeVisible()
})

test('dropdowns are themed listboxes with keyboard support', async ({ page }) => {
  await signIn(page)
  await page.goto('/dashboard')
  const combo = page.getByRole('combobox', { name: /language/i }).last()
  await combo.scrollIntoViewIfNeeded()
  await combo.click()
  const list = page.getByRole('listbox').filter({ has: page.getByRole('option', { name: /spanish|español/i }) }).last()
  await expect(list).toBeVisible()
  await expect(list.getByRole('option', { selected: true })).toContainText(/english/i)

  // The open list uses the site's surface colour, not the OS default.
  const bg = await list.evaluate((el) => getComputedStyle(el).backgroundColor)
  expect(bg).not.toBe('rgba(0, 0, 0, 0)')

  await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Enter')
  await expect(list).toBeHidden()
  await expect(combo).not.toContainText(/english/i)

  await combo.focus()
  await page.keyboard.press('ArrowDown')
  await expect(list).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(list).toBeHidden()
})

test('calendar shows the month and the portfolio without sideways scroll', async ({ page }) => {
  await signIn(page)
  await page.goto('/calendar')
  await expect(page.getByRole('grid')).toBeVisible()
  await expect(page.getByRole('gridcell')).toHaveCount(42)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('the admin console turns non-operators away', async ({ page }) => {
  await signIn(page)
  await page.goto('/admin')
  await expect(page).toHaveURL(/\/dashboard$/)
})
