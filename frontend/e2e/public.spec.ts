import { expect, test, type Page } from '@playwright/test'

const PUBLIC_PAGES = ['/', '/about', '/contact', '/privacy', '/terms', '/docs', '/status', '/login', '/signup', '/no-such-page']

async function expectNoSidewaysScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow, 'page is wider than the screen').toBeLessThanOrEqual(1)
}

for (const path of PUBLIC_PAGES) {
  test(`${path} renders without errors or sideways scroll`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(path)
    await expect(page.locator('h1').first()).toBeVisible()
    await expectNoSidewaysScroll(page)
    expect(errors).toEqual([])
  })
}

test('phone widths 360-430 px never scroll sideways', async ({ page }) => {
  for (const width of [360, 390, 430]) {
    await page.setViewportSize({ width, height: 800 })
    for (const path of ['/', '/login', '/about']) {
      await page.goto(path)
      await expect(page.locator('h1').first()).toBeVisible()
      await expectNoSidewaysScroll(page)
    }
  }
})

test('phone menu opens, links work, and Esc closes it', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'the menu button only exists below 960 px')
  await page.goto('/')
  const button = page.getByRole('button', { name: 'Open menu' })
  await button.click()
  await expect(page.getByRole('button', { name: 'Close menu' })).toHaveAttribute('aria-expanded', 'true')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Open menu' })).toHaveAttribute('aria-expanded', 'false')

  await page.getByRole('button', { name: 'Open menu' }).click()
  await page.locator('#public-menu').getByRole('link', { name: /about/i }).click()
  await expect(page).toHaveURL(/\/about$/)
})

test('logged-out visitors are sent to login from the app', async ({ page }) => {
  await page.goto('/dashboard')
  await expect(page).toHaveURL(/\/login/)
})

test('unknown routes show the 404 page', async ({ page }) => {
  await page.goto('/definitely-not-a-route')
  await expect(page.getByText(/404|not found/i).first()).toBeVisible()
})

test('theme toggle switches and persists', async ({ page }) => {
  await page.goto('/')
  const html = page.locator('html')
  const before = await html.getAttribute('data-theme')
  await page.getByRole('button', { name: 'Toggle color theme' }).first().click()
  await expect(html).not.toHaveAttribute('data-theme', before ?? '')
  await page.reload()
  await expect(html).not.toHaveAttribute('data-theme', before ?? '')
})

test('invite links survive the sign-in redirect', async ({ page }) => {
  await page.goto('/invite/abc123')
  await expect(page).toHaveURL(/\/login/)
  expect(await page.evaluate(() => sessionStorage.getItem('mos.next'))).toBe('/invite/abc123')
})
