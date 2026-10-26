import { expect, test, type Page } from '@playwright/test'

// Contacts in the UI, against a mocked backend: counts for everyone, addresses
// only for owners/admins/marketers, search and tag filters, and the CSV import
// wizard (map columns, say where consent came from, attest, see what was skipped).

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()
const COUNTS = { total: 3, subscribed: 2, pending: 0, unsubscribed: 1, bounced: 0, complained: 0, inactive: 1, cap: 1000 }
const CONTACTS = [
  { id: 'k1', email: 'ana@example.com', first_name: 'Ana', name: null, tags: ['vip', 'coffee'], status: 'subscribed',
    consent_source: 'checkout', created_at: now, consent_at: now, last_engaged_at: null },
  { id: 'k2', email: 'ben@example.com', first_name: null, name: 'Ben Ode', tags: ['coffee'], status: 'subscribed',
    consent_source: 'signup_form', created_at: now, consent_at: '2023-01-01T00:00:00Z', last_engaged_at: null },
  { id: 'k3', email: 'cy@example.com', first_name: 'Cy', name: null, tags: [], status: 'unsubscribed',
    consent_source: 'checkout', created_at: now, consent_at: now, last_engaged_at: null },
]

async function signIn(page: Page, role = 'owner') {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  const queries: string[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc === 'contact_counts') body = COUNTS
    else if (rpc === 'contact_tags') body = [{ tag: 'coffee', people: 2 }, { tag: 'vip', people: 1 }]
    else if (rpc === 'upsert_contacts') {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = { added: 2, updated: 0, skipped: [{ email: 'nope', reason: 'invalid' }] }
    } else if (rpc === 'export_contacts') {
      body = [{ email: 'ana@example.com', first_name: 'Ana', tags: ['vip', 'coffee'], status: 'subscribed', consent_source: 'checkout',
        consent_text: 'They agreed, "gladly"', attributes: { orders: 2 }, history: [{ kind: 'imported' }] }]
    } else if (rpc) {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = null
    } else if (url.includes('/contact_events')) {
      body = [{ id: 1, kind: 'clicked', actor: 'contact', created_at: now }, { id: 2, kind: 'imported', actor: 'user', created_at: now }]
    } else if (url.includes('/contacts') && /[?&]id=eq./.test(url)) {
      body = { consent_source: 'checkout', consent_note: 'website checkout, 2025', consent_text: 'Everyone in this file opted in.',
        consent_at: now, confirmed_at: null }
    } else if (url.includes('/contacts')) {
      queries.push(decodeURIComponent(url))
      body = CONTACTS
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({
      access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600,
      user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} },
    }))
  }, USER)
  return { rpcs, queries }
}

// The first load can be slow while several browsers start at once (the repo's usual 15 s allowance).
async function open(page: Page) {
  await page.goto('/contacts')
  await expect(page.getByRole('heading', { level: 1, name: 'Contacts' })).toBeVisible({ timeout: 15_000 })
}

test('counts and contacts with their consent source; search and tag filters query the list', async ({ page }) => {
  const { queries } = await signIn(page)
  await open(page)
  const counts = page.getByTestId('contact-counts')
  await expect(counts.getByText('2', { exact: true }).first()).toBeVisible()
  await expect(counts).toContainText('3 of 1,000')
  const list = page.getByTestId('contact-list')
  await expect(list.getByText('ana@example.com')).toBeVisible()
  await expect(list.getByTestId('contact-k1')).toContainText('Checkout')
  await expect(list.getByTestId('contact-k3')).toContainText('Unsubscribed')
  await expect(list.getByTestId('contact-k2')).toContainText('Inactive')  // no click or purchase in 24 months
  await expect(counts).toContainText('1 inactive')
  await page.getByRole('searchbox', { name: 'Search contacts' }).fill('ana')
  await expect.poll(() => queries.some((q) => q.includes('email.ilike.*ana*'))).toBe(true)
  await page.getByRole('button', { name: 'coffee · 2' }).click()
  await expect.poll(() => queries.some((q) => q.includes('tags=cs.{coffee}'))).toBe(true)
})

test('viewers see counts but no addresses', async ({ page }) => {
  await signIn(page, 'viewer')
  await open(page)
  await expect(page.getByTestId('contact-counts')).toBeVisible()
  await expect(page.getByTestId('contact-list')).toHaveCount(0)
  await expect(page.getByText(/Only owners, admins and marketers can see addresses/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Import contacts' })).toHaveCount(0)
})

test('importing a CSV: map columns, record consent, attest, then see what was skipped', async ({ page }) => {
  const { rpcs } = await signIn(page, 'marketer')
  await open(page)
  await page.getByRole('button', { name: 'Import contacts' }).click()
  const csv = 'Email,First name,Tags,Last order\n"dee@example.com",Dee,"vip;coffee",2026-09-01\neve@example.com,Eve,,\nnope,No,,\n'
  await page.getByLabel('CSV file').setInputFiles({ name: 'customers.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) })
  const wizard = page.getByTestId('import-wizard')
  await expect(wizard.getByText('3 rows')).toBeVisible()
  // Columns are matched from their headers; the email column is required.
  await expect(wizard.getByRole('combobox', { name: 'Email' })).toContainText('Email')
  await expect(wizard.getByRole('combobox', { name: 'Last purchase date' })).toContainText('Last order')
  const go = wizard.getByRole('button', { name: 'Import 3 contacts' })
  await expect(go).toBeDisabled()
  await wizard.getByRole('combobox', { name: 'Where did they opt in?' }).click()
  await page.getByRole('option', { name: 'At checkout' }).click()
  await wizard.getByLabel('Details (optional)').fill('website checkout, 2025')
  await expect(go).toBeDisabled() // not without the attestation
  await wizard.getByRole('checkbox', { name: /Everyone in this file opted in/ }).check()
  await go.click()
  await expect.poll(() => rpcs.filter((r) => r.name === 'upsert_contacts').length).toBe(1)
  const args = rpcs.find((r) => r.name === 'upsert_contacts')!.args as { p_rows: Record<string, unknown>[]; p_source: string; p_note: string; p_consent_text: string }
  expect(args.p_source).toBe('checkout')
  expect(args.p_note).toBe('website checkout, 2025')
  expect(args.p_consent_text).toMatch(/opted in/)
  expect(args.p_rows[0]).toEqual({ email: 'dee@example.com', first_name: 'Dee', tags: ['vip', 'coffee'], attributes: { last_purchase_at: '2026-09-01' } })
  expect(args.p_rows[1]).toEqual({ email: 'eve@example.com', first_name: 'Eve', tags: [], attributes: {} })
  const result = page.getByTestId('import-result')
  await expect(result).toContainText('2 added')
  await expect(result).toContainText('1 skipped')
  await result.getByText('1 skipped', { exact: true }).click()
  await expect(result.getByText('nope')).toBeVisible()
  await expect(result.getByText('Not a valid email address')).toBeVisible()
})

test('screenshots of contacts', async ({ page }, info) => {
  const dir = process.env.MEM_SHOTS
  test.skip(!dir, 'set MEM_SHOTS to a folder to capture them')
  await signIn(page)
  await open(page)
  await page.screenshot({ path: `${dir}/contacts-${info.project.name}.png`, fullPage: true })
})

test('the page fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page)
  await open(page)
  await page.getByRole('button', { name: 'Import contacts' }).click()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('owners see a person\'s consent record and history, export everyone, and erase someone (asked twice)', async ({ page }) => {
  const { rpcs } = await signIn(page, 'owner')
  await open(page)
  const row = page.getByTestId('contact-k1')
  await row.getByRole('button', { name: 'Consent and history' }).click()
  const detail = row.getByTestId('contact-detail')
  await expect(detail).toContainText('Checkout · website checkout, 2025')
  await expect(detail).toContainText('“Everyone in this file opted in.”')
  await expect(detail).toContainText('Clicked a link')
  await expect(detail).toContainText('the person')
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  const file = await download
  const stream = await file.createReadStream()
  const chunks: Buffer[] = []
  for await (const chunk of stream) chunks.push(chunk as Buffer)
  const csv = Buffer.concat(chunks).toString('utf8')
  expect(file.suggestedFilename()).toMatch(/^contacts-\d{4}-\d{2}-\d{2}\.csv$/)
  expect(csv.split('\n')[1]).toContain('ana@example.com,Ana,,,vip;coffee,subscribed,checkout,,"They agreed, ""gladly"""')
  await detail.getByRole('button', { name: 'Erase this person' }).click()
  expect(rpcs.some((r) => r.name === 'erase_contact')).toBe(false)
  await detail.getByRole('button', { name: 'Erase for good' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'erase_contact')?.args).toEqual({ p_contact: 'k1' })
})

test('marketers see the history but cannot export or erase', async ({ page }) => {
  await signIn(page, 'marketer')
  await open(page)
  await expect(page.getByRole('button', { name: 'Export CSV' })).toHaveCount(0)
  await page.getByTestId('contact-k1').getByRole('button', { name: 'Consent and history' }).click()
  await expect(page.getByTestId('contact-detail')).toContainText('Imported')
  await expect(page.getByRole('button', { name: 'Erase this person' })).toHaveCount(0)
})
