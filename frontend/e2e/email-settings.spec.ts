import { expect, test, type Page } from '@playwright/test'

// Settings → Email sending against a mocked backend: connecting a brand's own
// Resend account (live from a verified domain, or sandbox without one), the
// errors setup can hit, the postal-address requirement, preferences, the
// sign-up link, disconnecting, and members who can only look.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Brewline', personal: false }
const OFF = { connected: false, mode: null, domain: null, from_email: null, from_name: null, sandbox_to: null, webhook: false,
  webhook_ok_at: null, daily_limit: null, send_window_start: null, send_window_end: null, timezone: null, paused_reason: null,
  connected_at: null, postal_address: true, privacy_url: true, slug: 'brewline' }
const LIVE = { ...OFF, connected: true, mode: 'live', domain: 'brewline.coffee', from_email: 'hello@brewline.coffee', from_name: 'Brewline',
  webhook: true, daily_limit: 100, send_window_start: 9, send_window_end: 20, timezone: 'UTC', connected_at: new Date().toISOString() }
const DOMAINS = [{ id: 'dom_1', name: 'brewline.coffee', verified: true }, { id: 'dom_2', name: 'new.coffee', verified: false }]

interface Setup { status?: object; afterConnect?: object; role?: string; inspect?: object; connect?: [number, object] }

async function signIn(page: Page, s: Setup = {}) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  const invokes: Record<string, unknown>[] = []
  let status = s.status ?? OFF
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role: s.role ?? 'owner', organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc === 'email_status') body = status
    else if (rpc) {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = null
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/email-setup', async (route) => {
    const body = route.request().postDataJSON()
    invokes.push(body)
    if (body.action === 'inspect') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(s.inspect ?? { domains: DOMAINS, existing_webhooks: 0 }) })
    }
    const [code, payload] = s.connect ?? [200, { masked_key: '****9876', mode: body.mode, from_email: 'hello@brewline.coffee' }]
    if (code === 200) status = s.afterConnect ?? LIVE
    return route.fulfill({ status: code, contentType: 'application/json', body: JSON.stringify(payload) })
  })
  await page.route('**/functions/v1/**', (route) =>
    route.request().url().includes('email-setup') ? route.fallback() : route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({
      access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600,
      user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
    }))
  }, USER)
  return { rpcs, invokes }
}

async function open(page: Page) {
  await page.goto('/settings#email')
  const section = page.getByTestId('email-sending')
  await expect(section).toBeVisible({ timeout: 15_000 })
  return section
}

test('connecting live: check the key, pick the verified domain and address, connect', async ({ page }) => {
  const { invokes } = await signIn(page)
  const section = await open(page)
  await expect(section.getByText(/campaign emails only go to the test inbox/)).toBeVisible()
  await section.getByLabel('Resend API key (full access)').fill('re_full_key_1234')
  await section.getByRole('button', { name: 'Check key' }).click()
  await expect(section.getByRole('combobox', { name: 'Domain' })).toContainText('brewline.coffee')
  await expect(section.getByText('@brewline.coffee')).toBeVisible()
  await section.getByLabel('From address').fill('news')
  await section.getByLabel('Reply-to (optional)').fill('help@brewline.coffee')
  await section.getByRole('button', { name: 'Connect and go live' }).click()
  await expect(section.getByText('Sending as Brewline <hello@brewline.coffee>')).toBeVisible()
  expect(invokes[1]).toMatchObject({ action: 'connect', org_id: ORG.id, api_key: 're_full_key_1234', mode: 'live', domain_id: 'dom_1',
    from_local: 'news', from_name: 'Brewline', reply_to: 'help@brewline.coffee' })
  await expect(section.locator('code')).toHaveText(/\/join\/brewline$/)
})

test('without a verified domain it offers sandbox mode, proven with the Resend login email', async ({ page }) => {
  const sandbox = { ...LIVE, mode: 'sandbox', domain: null, from_email: 'onboarding@resend.dev', sandbox_to: 'ava@example.com' }
  const { invokes } = await signIn(page, { inspect: { domains: [DOMAINS[1]], existing_webhooks: 0 }, afterConnect: sandbox })
  const section = await open(page)
  await section.getByLabel('Resend API key (full access)').fill('re_full_key_1234')
  await section.getByRole('button', { name: 'Check key' }).click()
  await expect(section.getByText('No verified domain yet')).toBeVisible()
  const go = section.getByRole('button', { name: 'Connect in sandbox mode' })
  await expect(go).toBeDisabled()
  await section.getByLabel('The email you log in to Resend with').fill('ava@example.com')
  await go.click()
  await expect(section.getByText(/goes only to ava@example.com/)).toBeVisible()
  expect(invokes[1]).toMatchObject({ action: 'connect', mode: 'sandbox', sandbox_to: 'ava@example.com' })
})

test('a taken webhook slot is explained, not hidden', async ({ page }) => {
  await signIn(page, { connect: [400, { error: 'max webhooks', code: 'webhook_slot_taken' }] })
  const section = await open(page)
  await section.getByLabel('Resend API key (full access)').fill('re_full_key_1234')
  await section.getByRole('button', { name: 'Check key' }).click()
  await section.getByRole('button', { name: 'Connect and go live' }).click()
  await expect(section.getByRole('alert')).toContainText('webhook slot is in use')
})

test('no postal address in the brand kit: connecting waits for it', async ({ page }) => {
  await signIn(page, { status: { ...OFF, postal_address: false } })
  const section = await open(page)
  await section.getByLabel('Resend API key (full access)').fill('re_full_key_1234')
  await section.getByRole('button', { name: 'Check key' }).click()
  await expect(section.getByRole('alert')).toContainText('postal address')
  await expect(section.getByRole('button', { name: 'Connect and go live' })).toBeDisabled()
})

test('connected: managers set the daily limit and window, and disconnecting asks twice', async ({ page }) => {
  const { rpcs } = await signIn(page, { status: LIVE })
  const section = await open(page)
  await section.getByLabel('Emails per day').fill('60')
  await section.getByRole('button', { name: 'Save' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'update_email_preferences')?.args).toEqual(
    { p_org: ORG.id, p_daily_limit: 60, p_start: 9, p_end: 20, p_timezone: 'UTC' })
  await section.getByRole('button', { name: 'Disconnect' }).click()
  expect(rpcs.some((r) => r.name === 'disconnect_email')).toBe(false)
  await section.getByRole('button', { name: 'Disconnect for good' }).click()
  await expect.poll(() => rpcs.some((r) => r.name === 'disconnect_email')).toBe(true)
})

test('members who are not managers only see the status', async ({ page }) => {
  await signIn(page, { status: LIVE, role: 'marketer' })
  const section = await open(page)
  await expect(section.getByText('Sending as Brewline <hello@brewline.coffee>')).toBeVisible()
  await expect(section.getByLabel('Emails per day')).toHaveCount(0)
  await expect(section.getByRole('button', { name: 'Disconnect' })).toHaveCount(0)
})

test('the section fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page, { status: LIVE })
  await open(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('paused email says why, and a manager resumes it', async ({ page }) => {
  const { rpcs } = await signIn(page, { status: { ...LIVE, paused_reason: 'complaint rate 0.07% over the last 30 days' } })
  const section = await open(page)
  await expect(section.getByRole('alert')).toContainText('complaint rate 0.07%')
  await section.getByRole('button', { name: 'Resume email' }).click()
  await expect.poll(() => rpcs.some((r) => r.name === 'resume_email')).toBe(true)
})
