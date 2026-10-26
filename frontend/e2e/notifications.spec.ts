import { expect, test, type Page } from '@playwright/test'

// Notifications against a mocked backend: the top bar's bell (unread count,
// opening one marks it read and goes to it, mark all read, the email switch),
// and managers choosing who hears about approvals.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Brewline', personal: false }
const now = new Date().toISOString()
const NOTICES = [
  { id: 2, kind: 'gate_opened', title: 'Approval needed: Order-ahead coffee', body: 'Gate 2 (round 1) is waiting for approval.',
    link: '/campaigns/c1', created_at: now, read_at: null },
  { id: 1, kind: 'gate_overdue', title: 'Approval overdue', body: 'Gate 1 has waited 30 h.', link: '/campaigns/c2', created_at: now, read_at: null },
]
const MEMBERS = [
  { user_id: USER.id, role: 'owner', email: 'ava@example.com', username: 'ava', joined_at: now },
  { user_id: '33333333-3333-3333-3333-333333333333', role: 'approver', email: 'raj@example.com', username: 'raj', joined_at: now },
  { user_id: '44444444-4444-4444-4444-444444444444', role: 'marketer', email: 'mia@example.com', username: 'mia', joined_at: now },
]

async function signIn(page: Page, role = 'owner') {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc === 'org_members') body = MEMBERS
    else if (rpc) {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = rpc === 'mark_notifications_read' ? 1 : null
    } else if (url.includes('/notifications')) body = NOTICES
    else if (url.includes('/notification_prefs')) body = { email: true }
    else if (url.includes('/org_settings')) body = single ? { required_approvals: 1, forbid_self_approval: false, approval_sla_hours: 24,
      slack_webhook_url: null, notify_user_ids: [] } : []
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
  return { rpcs }
}

test('the bell counts unread notices; opening one marks it read and goes to the campaign', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/dashboard')
  const bell = page.getByRole('button', { name: 'Notifications, 2 unread' })
  await expect(bell).toBeVisible({ timeout: 15_000 })
  await expect(page.getByTestId('notification-count')).toHaveText('2')
  await bell.click()
  const panel = page.getByRole('dialog', { name: 'Notifications' })
  await expect(panel).toContainText('Gate 2 (round 1) is waiting for approval.')
  await panel.getByRole('link', { name: /Approval needed: Order-ahead coffee/ }).click()
  await expect(page).toHaveURL(/\/campaigns\/c1$/)
  await expect.poll(() => rpcs.find((r) => r.name === 'mark_notifications_read')?.args).toEqual({ p_ids: [2] })
})

test('mark all read, and turn the emails off for yourself', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/dashboard')
  await page.getByRole('button', { name: /Notifications/ }).click({ timeout: 15_000 })
  const panel = page.getByRole('dialog', { name: 'Notifications' })
  await panel.getByRole('button', { name: 'Mark all read' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'mark_notifications_read')?.args).toEqual({ p_ids: null })
  await expect(page.getByTestId('notification-count')).toHaveCount(0)
  await panel.getByRole('checkbox', { name: 'Also email me these' }).uncheck()
  await expect.poll(() => rpcs.find((r) => r.name === 'set_notification_email')?.args).toEqual({ p_on: false })
})

test('managers choose who hears about approvals (only people who can approve are offered)', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await page.goto('/settings#team')
  const people = page.getByTestId('notify-people')
  await expect(people).toContainText('No one chosen: everyone who can approve is told', { timeout: 15_000 })
  await expect(people.getByRole('checkbox')).toHaveCount(2)  // the owner and the approver; never the marketer
  await people.getByRole('checkbox', { name: /raj/ }).check()
  await expect(people).toContainText('Only the people ticked are told')
  await page.getByRole('button', { name: 'Save policy' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'set_notification_people')?.args).toEqual(
    { p_org: ORG.id, p_users: ['33333333-3333-3333-3333-333333333333'] })
})

test('the open panel fits a small phone', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 })
  await signIn(page)
  await page.goto('/dashboard')
  await page.getByRole('button', { name: /Notifications/ }).click({ timeout: 15_000 })
  await expect(page.getByRole('dialog', { name: 'Notifications' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
