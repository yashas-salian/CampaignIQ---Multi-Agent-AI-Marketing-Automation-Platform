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

test('persona cards show a 3D figure matching role and gender, guessing for older personas', async ({ page }) => {
  await signIn(page)
  const now = new Date().toISOString()
  const campaign = {
    id: 'c1', org_id: ORG.id, idea: 'Lesson planner for teachers', domain_category: 'education', feasibility_score: 70,
    feasibility_rationale: 'ok', status: 'awaiting_gate_1', current_round: 0, reddit_subreddit: null, email_to: null,
    cta_url: null, use_image_template: false, use_email_template: false, max_rounds: null, max_duration_minutes: null,
    campaign_summary: null, distributed_at: null, stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
  }
  const persona = (id: string, name: string, demographics: string, archetype: string | null, gender: string | null) => ({
    id, campaign_id: 'c1', name, demographics, psychographics: '-', channel_fit: 'email', messaging_angle: '-',
    is_primary: id === 'p1', archetype, gender,
  })
  const personas = [
    persona('p1', 'Maya', '34, maths teacher', 'teacher', 'female'),
    persona('p2', 'Dr. Okafor', 'hospital physician; she works nights', null, null), // older row: role + pronouns from text
    persona('p3', 'Alex Kim', 'lives downtown', null, null), // nothing to go on: initials, no figure
  ]
  await page.route('**/rest/v1/campaigns?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(campaign) }))
  await page.route('**/rest/v1/personas?*', (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(personas) })
      : route.fallback(),
  )
  await page.goto('/campaigns/c1')
  const figures = page.locator('figure img')
  await expect(figures).toHaveCount(2)
  await expect(figures.nth(0)).toHaveAttribute('src', '/personas/teacher-female.webp')
  await expect(figures.nth(1)).toHaveAttribute('src', '/personas/doctor-female.webp')
  await expect(page.getByText('AK', { exact: true })).toBeVisible()
  await expect(page.getByText('Teacher', { exact: true })).toBeVisible()
  // The image actually loads from public/ (no broken figure); it's lazy, so bring it into view first.
  await figures.nth(0).scrollIntoViewIfNeeded()
  await expect.poll(() => figures.nth(0).evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBeGreaterThan(0)
})

test('tools: recent runs live in a right-hand drawer that starts closed', async ({ page }) => {
  await signIn(page)
  await page.goto('/tools')
  const tab = page.getByRole('button', { name: /recent runs/i })
  await expect(tab).toHaveAttribute('aria-expanded', 'false')
  const drawer = page.getByRole('complementary', { name: /recent runs/i, includeHidden: true })
  await expect(drawer).toBeHidden()
  await tab.click()
  await expect(drawer).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(tab).toBeFocused()
})

test('settings: sections drawer starts closed and marks the section in view', async ({ page }) => {
  await signIn(page)
  await page.goto('/settings')
  const tab = page.getByRole('button', { name: /sections/i })
  await expect(tab).toHaveAttribute('aria-expanded', 'false')
  await tab.click()
  const nav = page.getByRole('navigation', { name: /sections/i })
  await expect(nav).toBeVisible()
  await expect(nav.locator('[aria-current="location"]')).toHaveCount(1)

  // Jumping to a section closes the drawer and marks that section.
  const privacy = nav.getByRole('link', { name: /privacy/i })
  await privacy.click()
  await expect(nav).toBeHidden()
  await tab.click()
  await expect(privacy).toHaveAttribute('aria-current', 'location')
  // The current section keeps the site's orange fill + left-to-right underline drawn (polled: it animates in).
  const wipe = privacy.locator('.link-wipe')
  await expect.poll(() => wipe.evaluate((el) => getComputedStyle(el).backgroundPositionX)).toMatch(/^0(px|%)$/)
  await expect
    .poll(() => wipe.evaluate((el) => getComputedStyle(el, '::after').transform))
    .toBe('matrix(1, 0, 0, 1, 0, 0)')
  // Other sections rest undrawn.
  const other = nav.getByRole('link', { name: /account/i }).locator('.link-wipe')
  expect(await other.evaluate((el) => getComputedStyle(el, '::after').transform)).toBe('matrix(0, 0, 0, 1, 0, 0)')
})

test('settings: scrolling to the bottom marks the last section, a picked section stays marked', async ({ page }) => {
  await signIn(page)
  await page.goto('/settings')
  const tab = page.getByRole('button', { name: /sections/i })
  const nav = page.getByRole('navigation', { name: /sections/i, includeHidden: true })
  const currentLabel = () => nav.locator('[aria-current="location"]').textContent({ timeout: 2000 })

  // Scroll by hand to the very bottom: the short last section (Privacy) must be current.
  await page.mouse.move(200, 400)
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, 1200)
  await expect.poll(currentLabel).toMatch(/privacy/i)

  // Pick a section that can't scroll all the way up: it stays the current one.
  await tab.click()
  await nav.getByRole('link', { name: /templates/i }).click()
  await page.waitForTimeout(800)
  await expect.poll(currentLabel).toMatch(/templates/i)
})
