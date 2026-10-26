import { expect, test, type Page } from '@playwright/test'

// Brand memory in the UI, against a mocked backend: lessons waiting for review
// (confirm before use), lessons in use with their provenance, a lesson that
// conflicts with policy marked as not used, correcting and deleting, recording a
// new lesson (brand-wide rules only for owners/admins), viewers read only, and
// the Gate 2 copy editor asking why when an edit changes the ad substantially.

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()
const days = (n: number) => new Date(Date.now() + n * 86_400_000).toISOString()

const base = {
  org_id: ORG.id, conditions: {}, directives: {}, source_campaign_id: null, confidence: 0.7, author_id: null, reviewed_at: null,
  expires_at: null, supersedes: null, policy_conflict: null, use_count: 0, last_used_at: null, created_at: now, review_at: days(80),
}
const LESSONS = [
  { ...base, id: 'p1', type: 'AUDIENCE_INSIGHT', lesson: 'Never promise delivery times, we cannot meet them at rush hour', scope: 'context',
    status: 'proposed', author_kind: 'system', conditions: { domains: ['food_beverage'] },
    evidence: [{ kind: 'gate_reject', excerpt: 'Never promise delivery times, we cannot meet them at rush hour', campaign_id: 'c1', round: 2 }] },
  { ...base, id: 'a1', type: 'BRAND_PREFERENCE', lesson: 'Never call our coffee cheap: customers read it as low quality. Say good value.', scope: 'brand',
    status: 'active', author_kind: 'person', confidence: 0.9, use_count: 7, directives: { avoid_terms: ['cheap'], prefer_terms: ['good value'] },
    evidence: [{ kind: 'copy_edit', campaign_id: 'c1', round: 1, before: 'Cheap coffee for commuters', after: 'Good-value coffee for commuters' }] },
  { ...base, id: 'a2', type: 'FAILED_EXPERIMENT', lesson: 'Humorous ads underperformed for our coffee in two tests.', scope: 'context',
    status: 'active', author_kind: 'system', confidence: 0.8, conditions: { domains: ['food_beverage'], channels: ['email'] },
    directives: { avoid_tones: ['humorous'] }, review_at: days(-3), evidence: [{ kind: 'experiment', ref: 'e1', excerpt: 'NEGATIVE_IMPACT' }] },
  { ...base, id: 'a3', type: 'POLICY_DECISION', lesson: 'Tell customers our coffee is guaranteed to make their morning better.', scope: 'brand',
    status: 'active', author_kind: 'person', policy_conflict: '"guaranteed" is an absolute or regulated claim', evidence: [] },
  { ...base, id: 'x1', type: 'CAMPAIGN_LESSON', lesson: 'Mention the pumpkin spice latte in autumn emails.', scope: 'context', status: 'expired',
    author_kind: 'person', evidence: [] },
]

async function signIn(page: Page, role = 'owner', opts: { campaign?: object; iterations?: object[]; gate?: object } = {}) {
  const rpcs: { name: string; args: Record<string, unknown> }[] = []
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body: unknown = single ? null : []
    const rpc = url.match(/\/rpc\/(\w+)/)?.[1]
    if (url.includes('/memberships')) body = [{ role, organizations: ORG }]
    else if (rpc === 'org_usage') body = { plan: 'free', limits: {}, used: {} }
    else if (rpc === 'org_approval_policy') body = { required_approvals: 1 }
    else if (rpc) {
      rpcs.push({ name: rpc, args: route.request().postDataJSON() })
      body = rpc === 'add_brand_lesson' ? 'n1' : null
    } else if (url.includes('/brand_memories')) body = LESSONS
    else if (url.includes('/campaigns?') && opts.campaign) body = single ? opts.campaign : [opts.campaign]
    else if (url.includes('/campaigns?') && url.includes('select=id%2Cidea')) body = [{ id: 'c1', idea: 'Order-ahead coffee for commuters who hate queues at the station every morning' }]
    else if (url.includes('/iterations') && opts.iterations) body = opts.iterations
    else if (url.includes('/gate_decisions') && opts.gate) body = opts.gate
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/storage/v1/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
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

// The first load can be slow while several browsers start at once (the repo's usual 15 s allowance).
async function open(page: Page) {
  await page.goto('/memory')
  await expect(page.getByRole('heading', { level: 1, name: 'Brand memory' })).toBeVisible({ timeout: 15_000 })
}

test('suggested lessons wait for a person, with where they came from', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await open(page)
  const queue = page.getByTestId('review-queue')
  await expect(queue.getByRole('heading', { name: '1 lesson to review' })).toBeVisible()
  const card = queue.getByTestId('lesson-p1')
  await expect(card.getByText('Suggested by the system', { exact: false })).toBeAttached()
  await card.getByText(/Where it came from/).click()
  await expect(card.getByText('Rejected at a gate')).toBeVisible()
  await expect(card.getByRole('link', { name: 'From campaign: Order-ahead coffee for commuters who hate queues at the s…' }))
    .toHaveAttribute('href', '/campaigns/c1')
  await card.getByRole('button', { name: 'Confirm' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'review_brand_lesson')?.args).toEqual({ p_memory: 'p1', p_accept: true, p_note: null })
})

test('lessons in use show their scope, conditions, directives and review state; a policy conflict is marked unused', async ({ page }) => {
  await signIn(page)
  await open(page)
  const active = page.getByTestId('active-lessons')
  const rule = active.getByTestId('lesson-a1')
  await expect(rule.getByText('Brand-wide rule')).toBeVisible()
  await expect(rule.getByText('Applies to every campaign.')).toBeVisible()
  await expect(rule.getByText('good value', { exact: true })).toBeVisible()
  await rule.getByText(/Where it came from/).click()
  await expect(rule.getByText(/Before: “Cheap coffee for commuters” → After: “Good-value coffee for commuters”/)).toBeVisible()
  await expect(rule.getByText(/used 7 times/)).toBeVisible()
  const failed = active.getByTestId('lesson-a2')
  await expect(failed.getByText('review overdue')).toBeVisible()
  await expect(failed.getByText('humorous', { exact: true })).toBeVisible()
  await expect(failed.getByText('Food & beverage', { exact: true })).toBeVisible()
  await expect(failed.getByRole('button', { name: 'Still true' })).toBeVisible()
  await expect(active.getByTestId('lesson-a3').getByText(/Not used: it conflicts with a current policy/)).toBeVisible()
  await active.getByRole('button', { name: 'Failed experiment' }).click()
  await expect(active.getByTestId('lesson-a1')).toHaveCount(0)
  await expect(page.getByTestId('memory-eval')).toContainText('39%')
})

test('correcting keeps history and needs a reason; deleting asks twice', async ({ page }) => {
  const { rpcs } = await signIn(page)
  await open(page)
  const card = page.getByTestId('lesson-a1')
  await card.getByRole('button', { name: 'Correct' }).click()
  const save = card.getByRole('button', { name: 'Save correction' })
  await expect(save).toBeDisabled()
  await card.getByLabel('Lesson').fill('Never call our coffee cheap or budget: say good value.')
  await card.getByLabel('What was wrong with it?').fill('Budget tested badly too')
  await save.click()
  await expect.poll(() => rpcs.find((r) => r.name === 'correct_brand_lesson')?.args).toMatchObject(
    { p_memory: 'a1', p_lesson: 'Never call our coffee cheap or budget: say good value.', p_scope: 'brand', p_note: 'Budget tested badly too' })
  const other = page.getByTestId('lesson-a2')
  await other.getByRole('button', { name: 'Delete' }).click()
  expect(rpcs.some((r) => r.name === 'delete_brand_lesson')).toBe(false)
  await other.getByRole('button', { name: 'Delete for good' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'delete_brand_lesson')?.args).toEqual({ p_memory: 'a2' })
  await expect(page.getByText(/1 earlier lesson/)).toBeVisible()
})

test('recording a lesson; a brand-wide rule is for owners and admins only', async ({ page }) => {
  const { rpcs } = await signIn(page, 'marketer')
  await open(page)
  const form = page.getByTestId('add-lesson')
  await form.getByRole('combobox', { name: 'Scope' }).click()
  await expect(page.getByRole('option', { name: 'Brand-wide rule' })).toBeDisabled()
  await page.keyboard.press('Escape')
  await form.getByLabel('Lesson', { exact: true }).fill('Customers over 55 ignore slang: write plainly.')
  await form.getByRole('checkbox', { name: 'Food & beverage' }).check()
  await form.getByRole('checkbox', { name: '55+' }).check()
  await form.getByLabel('Words to avoid (optional)').fill('vibes, lit')
  await form.getByRole('button', { name: 'Save lesson' }).click()
  await expect.poll(() => rpcs.find((r) => r.name === 'add_brand_lesson')?.args).toMatchObject({
    p_type: 'BRAND_PREFERENCE', p_lesson: 'Customers over 55 ignore slang: write plainly.', p_scope: 'context',
    p_conditions: { domains: ['food_beverage'], age_brackets: ['55+'] }, p_directives: { avoid_terms: ['vibes', 'lit'] },
  })
})

test('viewers read lessons but cannot change them', async ({ page }) => {
  await signIn(page, 'viewer')
  await open(page)
  await expect(page.getByTestId('lesson-a1')).toBeVisible()
  await expect(page.getByTestId('add-lesson')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Confirm' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Correct' })).toHaveCount(0)
})

test('Gate 2: a substantial edit asks why, and can be remembered', async ({ page }) => {
  const campaign = { id: 'c1', org_id: ORG.id, idea: 'Order-ahead coffee', domain_category: 'food_beverage', feasibility_score: 60,
    feasibility_rationale: 'ok', status: 'awaiting_gate_2', current_round: 1, email_to: null, cta_url: null, max_rounds: 3,
    campaign_summary: null, stop_requested: false, target_language: 'en', created_at: now, updated_at: now }
  const iteration = { id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1, copy_text: 'Cheap coffee for commuters, ready when you arrive.',
    image_prompt: 'cup', preflight_score: 70, preflight_passed: true, image_style: 'minimalist', copy_tone: 'direct_factual', arm_index: 0 }
  const { rpcs } = await signIn(page, 'owner', { campaign, iterations: [iteration],
    gate: { id: 'g2', campaign_id: 'c1', gate_number: 2, round_number: 1, decision: null, decided_at: null } })
  await page.goto('/campaigns/c1')
  const editor = page.getByLabel('Edit the copy before approving')
  await expect(editor).toBeVisible({ timeout: 15_000 })
  await editor.fill('Cheap coffee for commuters, ready when you arrive!')  // a small fix: no reason needed
  await expect(page.getByTestId('edit-reason')).toHaveCount(0)
  await editor.fill('Good-value coffee waiting for you the moment you step off the train.')
  await expect(page.getByTestId('edit-reason')).toBeVisible()
  const save = page.getByRole('button', { name: 'Save edit' })
  await expect(save).toBeDisabled()
  await page.getByLabel(/This changes the ad substantially/).fill('Cheap reads as low quality for our brand')
  await page.getByRole('checkbox', { name: 'Remember this for future campaigns' }).check()
  await save.click()
  await expect.poll(() => rpcs.find((r) => r.name === 'edit_round_copy')?.args).toEqual({
    p_campaign: 'c1', p_round: 1, p_variant: 'a', p_text: 'Good-value coffee waiting for you the moment you step off the train.',
    p_reason: 'Cheap reads as low quality for our brand', p_remember: true,
  })
})

// Review screenshots: MEM_SHOTS=<dir> npx playwright test e2e/memory.spec.ts -g screenshots
test('screenshots of brand memory', async ({ page }, info) => {
  const dir = process.env.MEM_SHOTS
  test.skip(!dir, 'set MEM_SHOTS to a folder to capture them')
  await signIn(page)
  await open(page)
  await page.getByTestId('lesson-a1').getByText(/Where it came from/).click()
  await page.screenshot({ path: `${dir}/memory-${info.project.name}.png`, fullPage: true })
})

test('the page fits a phone without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 })
  await signIn(page)
  await open(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
