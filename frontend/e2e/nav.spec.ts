import { expect, test, type Page } from '@playwright/test'

// Navigation shows only what the visitor can use right now: signed out, public
// links and log in / sign up; signed in, the app (top bar + sidebar) on app pages
// and a Dashboard button on public ones; in the sidebar, nothing their role can't do.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }

async function backend(page: Page, role: string | null) {
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (url.includes('/rpc/org_usage')) body = { plan: 'free', limits: {}, used: {} }
    else if (url.includes('/rpc/')) body = null
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  if (!role) return
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({
      access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600,
      user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
    }))
  }, USER)
}

const APP_LINKS = [/^competitors$/i, /^playbooks$/i, /^tools$/i, /run history/i, /^calendar$/i]

test('a signed-out visitor sees only public links, on every public page', async ({ page }) => {
  await backend(page, null)
  for (const path of ['/', '/contact', '/about', '/docs', '/status', '/privacy', '/terms', '/nope']) {
    await page.goto(path)
    const header = page.getByRole('banner').first()
    await expect(header).toBeVisible({ timeout: 15_000 })
    await expect(header.getByRole('link', { name: 'MarketingOS' })).toBeVisible()
    await expect(header.getByRole('link', { name: /get started/i })).toBeVisible()  // (log in is in the phone menu)
    await expect(page.getByRole('link', { name: /dashboard/i })).toHaveCount(0)
    await expect(page.getByRole('navigation', { name: /^main$/i })).toHaveCount(0)
    for (const name of APP_LINKS) await expect(page.getByRole('link', { name })).toHaveCount(0)
  }
})

test('signed in on a public page: the navbar offers the dashboard, never log in or sign up, and no sidebar', async ({ page }) => {
  await backend(page, 'owner')
  for (const path of ['/contact', '/docs']) {
    await page.goto(path)
    await expect(page.getByRole('banner').first().getByRole('link', { name: /dashboard/i })).toBeVisible({ timeout: 15_000 })
    await expect(page.getByRole('link', { name: 'Log in' })).toHaveCount(0)
    await expect(page.getByRole('link', { name: /get started/i })).toHaveCount(0)
    await expect(page.getByRole('navigation', { name: /^main$/i })).toHaveCount(0)
  }
})

test('the docs table of contents marks the section in view, and a picked one', async ({ page }) => {
  await backend(page, null)
  await page.goto('/docs')
  const toc = page.getByRole('navigation', { name: 'On this page' })
  const current = () => toc.locator('[aria-current="location"]')
  await expect(current()).toHaveText('Getting started', { timeout: 15_000 })
  // Scrolling by hand moves the mark.
  await page.locator('#ab').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 100))
  await expect(current()).toHaveAttribute('href', '#ab')
  // At the bottom, the last section is marked even if it can't reach the line.
  await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight))
  await expect(current()).toHaveAttribute('href', '#privacy')
  // A picked section is marked straight away.
  await toc.locator('a[href="#teams"]').click()
  await expect(current()).toHaveAttribute('href', '#teams')
  await expect(toc.locator('[aria-current="location"]')).toHaveCount(1)
})

test('the sidebar only offers what the role can do', async ({ page }, info) => {
  test.skip(info.project.name === 'phone', 'the phone drawer is covered by the sidebar test in app.spec.ts')
  await backend(page, 'viewer')
  await page.goto('/dashboard')
  const nav = page.getByRole('navigation', { name: /^main$/i })
  await expect(nav.getByRole('link', { name: /^dashboard$/i })).toBeAttached({ timeout: 15_000 })
  await expect(nav.getByRole('link', { name: /new campaign/i })).toHaveCount(0)  // viewers can't start campaigns
  await expect(nav.getByRole('link', { name: /^admin/i })).toHaveCount(0)        // nor open the operators' console
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await backend(page, 'marketer')
  await page.goto('/dashboard')
  await expect(nav.getByRole('link', { name: /new campaign/i })).toBeAttached({ timeout: 15_000 })
})
