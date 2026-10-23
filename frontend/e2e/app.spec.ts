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
  // No 3D models here: this checks the picture fallback (the 3D path has its own test).
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.goto('/campaigns/c1')
  // The 2D figure stands in until a 3D model exists for that role and gender.
  const figures = page.locator('img[src^="/personas/"]')
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

// Desktop: the rail slides out when the cursor reaches it. Phones: the menu button opens a drawer.
async function openNav(page: Page, project: string) {
  const nav = page.getByRole('navigation', { name: /^main$/i })
  if (project === 'phone') {
    await page.getByRole('button', { name: /^menu$/i }).click()
  } else {
    await nav.hover({ position: { x: 20, y: 120 } })
  }
  await expect.poll(async () => (await nav.boundingBox())?.width ?? 0).toBeGreaterThan(200)
  return nav
}

test('the sidebar opens from the left on every app page and lists every feature', async ({ page }, info) => {
  await signIn(page)
  await page.goto('/dashboard')
  const nav = page.getByRole('navigation', { name: /^main$/i })
  if (info.project.name !== 'phone') {
    // A slim rail until the cursor arrives.
    await expect.poll(async () => (await nav.boundingBox())?.width ?? 0).toBeLessThan(80)
  }
  await openNav(page, info.project.name)
  for (const name of [/new campaign/i, /^dashboard$/i, /^calendar$/i, /^tools$/i, /run history/i, /^playbooks$/i, /our ai model/i, /^settings$/i])
    await expect(nav.getByRole('link', { name })).toBeVisible()
  await expect(nav.getByRole('link', { name: /^dashboard$/i })).toHaveAttribute('aria-current', 'page')

  await nav.getByRole('link', { name: /^playbooks$/i }).click()
  await expect(page).toHaveURL(/\/playbooks$/)
  // Navigating closes it again.
  if (info.project.name === 'phone') await expect(nav).toBeHidden()
  else {
    await page.mouse.move(900, 500)
    await expect.poll(async () => (await nav.boundingBox())?.width ?? 0).toBeLessThan(80)
  }
})

test('settings: its sections live in the sidebar, and the one in view is marked', async ({ page }, info) => {
  await signIn(page)
  await page.goto('/settings')
  const nav = await openNav(page, info.project.name)
  const sections = nav.getByRole('list', { name: /sections/i })
  await expect(sections.locator('[aria-current="location"]')).toHaveCount(1)

  // Jumping to a section marks it, with the site's orange fill + left-to-right underline.
  await sections.getByRole('link', { name: /privacy/i }).click()
  await openNav(page, info.project.name)
  const privacy = sections.getByRole('link', { name: /privacy/i })
  await expect(privacy).toHaveAttribute('aria-current', 'location')
  const wipe = privacy.locator('.link-wipe')
  await expect.poll(() => wipe.evaluate((el) => getComputedStyle(el).backgroundPositionX)).toMatch(/^0(px|%)$/)
  await expect.poll(() => wipe.evaluate((el) => getComputedStyle(el, '::after').transform)).toBe('matrix(1, 0, 0, 1, 0, 0)')
  const other = sections.getByRole('link', { name: /account/i }).locator('.link-wipe')
  expect(await other.evaluate((el) => getComputedStyle(el, '::after').transform)).toBe('matrix(0, 0, 0, 1, 0, 0)')
})

test('settings: scrolling to the bottom marks the last section, a picked section stays marked', async ({ page }, info) => {
  await signIn(page)
  await page.goto('/settings')
  const sections = page.getByRole('navigation', { name: /^main$/i, includeHidden: true }).getByRole('list', { name: /sections/i, includeHidden: true })
  const currentLabel = () => sections.locator('[aria-current="location"]').textContent({ timeout: 2000 })

  // Scroll by hand to the very bottom: the short last section (Privacy) must be current.
  await page.mouse.move(700, 400)
  for (let i = 0; i < 40; i++) await page.mouse.wheel(0, 1200)
  await expect.poll(currentLabel).toMatch(/privacy/i)

  // Pick a section that can't scroll all the way up: it stays the current one.
  await openNav(page, info.project.name)
  await sections.getByRole('link', { name: /templates/i }).click()
  await page.waitForTimeout(800)
  await expect.poll(currentLabel).toMatch(/templates/i)
})

// A one-triangle model, enough to prove the 3D path mounts a canvas.
const TINY_GLB = 'Z2xURgIAAACYAQAAWAEAAEpTT057ImFzc2V0Ijp7InZlcnNpb24iOiIyLjAifSwic2NlbmUiOjAsInNjZW5lcyI6W3sibm9kZXMiOlswXX1dLCJub2RlcyI6W3sibWVzaCI6MH1dLCJtZXNoZXMiOlt7InByaW1pdGl2ZXMiOlt7ImF0dHJpYnV0ZXMiOnsiUE9TSVRJT04iOjB9fV19XSwiYnVmZmVycyI6W3siYnl0ZUxlbmd0aCI6MzZ9XSwiYnVmZmVyVmlld3MiOlt7ImJ1ZmZlciI6MCwiYnl0ZU9mZnNldCI6MCwiYnl0ZUxlbmd0aCI6MzZ9XSwiYWNjZXNzb3JzIjpbeyJidWZmZXJWaWV3IjowLCJjb21wb25lbnRUeXBlIjo1MTI2LCJjb3VudCI6MywidHlwZSI6IlZFQzMiLCJtaW4iOlstMC41LDAsMF0sIm1heCI6WzAuNSwxLjgsMF19XX0gICQAAABCSU4AAAAAvwAAAAAAAAAAAAAAPwAAAAAAAAAAAAAAAGZm5j8AAAAA'

test('a persona with a 3D model shows a rotatable canvas instead of the picture', async ({ page }) => {
  await signIn(page)
  const now = new Date().toISOString()
  const campaign = {
    id: 'c1', org_id: ORG.id, idea: 'Lesson planner', domain_category: 'education', feasibility_score: 70, feasibility_rationale: 'ok',
    status: 'awaiting_gate_1', current_round: 0, reddit_subreddit: null, email_to: null, cta_url: null, use_image_template: false,
    use_email_template: false, max_rounds: null, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
    stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
  }
  const persona = { id: 'p1', campaign_id: 'c1', name: 'Maya', demographics: '34', psychographics: '-', channel_fit: 'email', messaging_angle: '-', is_primary: true, archetype: 'teacher', gender: 'female' }
  await page.route('**/rest/v1/campaigns?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(campaign) }))
  await page.route('**/rest/v1/personas?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([persona]) }))
  await page.route('**/personas/models/teacher-female.glb', (route) =>
    route.fulfill({ status: 200, contentType: 'model/gltf-binary', body: Buffer.from(TINY_GLB, 'base64') }),
  )
  await page.goto('/campaigns/c1')
  // Software WebGL in CI is slow under parallel load: allow it time to build the scene.
  const stage = page.getByRole('img', { name: /3d figure: teacher/i })
  await expect(stage).toBeVisible({ timeout: 20000 })
  await expect(stage.locator('canvas')).toHaveCount(1, { timeout: 20000 })
  await expect(stage).toHaveAttribute('data-ready', 'true', { timeout: 20000 })
  // Keyboard turning works without a mouse.
  await stage.focus()
  await page.keyboard.press('ArrowRight')
})

const RUNS = [
  { id: 'r1', capability: 'personas', status: 'completed', params: { idea: 'Meal kits for night-shift nurses', target_language: 'en' }, result: [{ name: 'Priya' }, { name: 'Omar' }], error: null, created_at: '2026-10-20T10:00:00Z' },
  { id: 'r2', capability: 'feasibility', status: 'failed', params: { idea: 'Budget app for freelancers', target_language: 'es' }, result: null, error: 'Groq quota exceeded', created_at: '2026-09-05T10:00:00Z' },
  { id: 'r3', capability: 'image', status: 'completed', params: { prompt: 'Sunrise over a running track' }, result: { image_base64: 'x' }, error: null, created_at: '2025-12-31T10:00:00Z' },
]

test('tools: the input clears after Run, and the drawer links to the full history', async ({ page }) => {
  await signIn(page)
  await page.route('**/functions/v1/trigger-capability-run', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ run_id: 'new-run' }) }))
  await page.goto('/tools')
  const box = page.getByPlaceholder(/./).first()
  await box.fill('Protein snacks for gamers')
  await page.getByRole('button', { name: /^run/i }).click()
  await expect(box).toHaveValue('')

  await page.getByRole('button', { name: /recent runs/i }).click()
  await page.getByRole('link', { name: /see all history/i }).click()
  await expect(page).toHaveURL(/\/tools\/history$/)
})

test('tools history: search and filters cover every run, and a run opens back in Tools', async ({ page }) => {
  await signIn(page)
  await page.route('**/rest/v1/capability_runs?*', (route) => {
    const url = route.request().url()
    const one = /id=eq\.([^&]+)/.exec(url)?.[1]
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(one ? RUNS.find((r) => r.id === one) ?? null : RUNS) })
  })
  await page.goto('/tools/history')
  await expect(page.getByText('3 runs')).toBeVisible()

  // Search reaches into results and errors, not just the typed idea.
  await page.getByRole('textbox', { name: /search runs/i }).fill('priya')
  await expect(page.getByText('1 run', { exact: true })).toBeVisible()
  await expect(page.getByText(/night-shift nurses/)).toBeVisible()
  await page.getByRole('textbox', { name: /search runs/i }).fill('quota')
  await expect(page.getByText(/budget app for freelancers/i)).toBeVisible()

  // Filters: a year, then clear.
  await page.getByRole('button', { name: /clear filters/i }).first().click()
  await page.getByRole('combobox', { name: /^when$/i }).click()
  await page.getByRole('option', { name: /a year/i }).click()
  await page.getByRole('combobox', { name: /^year$/i }).click()
  await page.getByRole('option', { name: '2025' }).click()
  await expect(page.getByText(/sunrise over a running track/i)).toBeVisible()
  await expect(page.getByText(/night-shift nurses/)).toHaveCount(0)

  await page.getByText(/sunrise over a running track/i).click()
  await expect(page).toHaveURL(/\/tools$/)
})

test('campaign page: interview a persona, and Gate 2 shows the audience verdict and why this ad', async ({ page }) => {
  await signIn(page)
  const now = new Date().toISOString()
  const campaign = {
    id: 'c1', org_id: ORG.id, idea: 'Lesson planner', domain_category: 'education', feasibility_score: 70, feasibility_rationale: 'ok',
    status: 'awaiting_gate_2', current_round: 1, reddit_subreddit: null, email_to: null, cta_url: null, use_image_template: false,
    use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null, distributed_at: null,
    stop_requested: false, target_language: 'en', created_at: now, updated_at: now,
  }
  const persona = { id: '9b2f1c7e-0000-4000-8000-000000000001', campaign_id: 'c1', name: 'Maya Rao', demographics: '34, maths teacher', psychographics: 'busy', channel_fit: 'email', messaging_angle: 'saves time', is_primary: true, archetype: 'teacher', gender: 'female' }
  const iteration = {
    id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1, copy_text: 'Plan a week of lessons in 10 minutes.', image_prompt: 'desk',
    preflight_score: 64, preflight_passed: true, bluesky_post_uri: null, reddit_post_url: null, email_id: null, image_style: 'minimalist', copy_tone: 'direct_factual', arm_index: 0, guardrail_flags: null,
    focus_group: { reactions: [{ name: 'Maya Rao', archetype: 'teacher', gender: 'female', reaction: 'click', likelihood: 82, quote: 'This would save my Sundays.' }], verdict: { click: 1, scroll: 0, object: 0 }, average_likelihood: 82 },
    arm_explain: { algorithm: 'LinUCB', alpha: 0.5, context: { age_bracket: '25-34', income_tier: 'mid', domain_category: 'education', channels: ['email'] }, chosen: { arm_index: 0, image_style: 'minimalist', copy_tone: 'direct_factual', expected: 0, bonus: 0.5, score: 0.5, pulls: 0, mean_reward: null }, mode: 'explore', rank: 1, alternatives: [], arms_tried: 0, total_rounds: 0 },
  }
  await page.route('**/rest/v1/campaigns?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(campaign) }))
  await page.route('**/rest/v1/personas?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([persona]) }))
  await page.route('**/rest/v1/iterations?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([iteration]) }))
  await page.route('**/rest/v1/gate_decisions?*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'g1', campaign_id: 'c1', gate_number: 2, round_number: 1, decision: null, decided_at: null }) }),
  )
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.route('**/functions/v1/persona-chat', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ answer: 'Honestly, about 300 rupees a month.', remaining: 19 }) }),
  )
  await page.goto('/campaigns/c1')

  // Gate 2: the personas' verdict, before approving.
  await expect(page.getByRole('region', { name: /audience verdict/i }).first()).toBeVisible()
  await expect(page.getByText('This would save my Sundays.').first()).toBeVisible()
  // Why this ad?
  await page.getByText(/why this ad\?/i).first().click()
  await expect(page.getByText(/to learn/i).first()).toBeVisible()

  // Interview the persona.
  await page.getByRole('button', { name: /interview maya/i }).click()
  const chat = page.getByRole('dialog', { name: /interview with maya rao/i })
  await expect(chat).toBeVisible()
  await chat.getByRole('textbox').fill('What price feels fair?')
  await chat.getByRole('button', { name: /send/i }).click()
  await expect(chat.getByText('Honestly, about 300 rupees a month.')).toBeVisible()
  await expect(chat.getByText(/19 questions left/i)).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(chat).toBeHidden()
})

test('model card shows our model against its base, the learning loop and deployment', async ({ page }) => {
  await signIn(page)
  await page.route('**/rest/v1/rpc/model_card', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      versions: [{ version: 'v1', revision: null, trained_at: '2026-10-21T10:00:00Z', base_model: 'Qwen2.5-1.5B-Instruct', method: 'LoRA', data: { synthetic_examples: 560, corrections_used: 0, labels: 12 }, metrics: { golden: 0.8333, golden_n: 18, heldout: 0.75, heldout_n: 96 }, baseline_metrics: { label: 'Base Qwen2.5-1.5B', golden: 0.5556, heldout: 0.5417 }, notes: null }],
      deployment: { active_revision: null, candidate_revision: null, mode: 'off', canary_percent: 0, updated_at: '2026-10-21T10:00:00Z' },
      shadow: { compared: 0, agreement: null }, corrections: { total: 4, since_last_training: 4, last_30_days: 4 },
    }) }),
  )
  await page.goto('/models')
  await expect(page.getByRole('heading', { name: /domain classifier/i })).toBeVisible()
  await expect(page.getByText('83%').first()).toBeVisible()
  await expect(page.getByText('+28 pts')).toBeVisible()
})

test('market moments show on the dashboard and can be dismissed', async ({ page }) => {
  await signIn(page)
  let dismissed = false
  await page.route('**/rest/v1/market_alerts?*', (route) => {
    if (route.request().method() === 'PATCH') {
      dismissed = true
      return route.fulfill({ status: 204, body: '' })
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { id: 7, campaign_id: 'c1', kind: 'trend', created_at: new Date().toISOString(), campaigns: { idea: 'Budget app' },
        detail: { keyword: 'budget app', value: 72, baseline: 30, ratio: 2.4 } },
    ]) })
  })
  await page.goto('/dashboard')
  const moments = page.getByRole('region', { name: /market moments/i })
  await expect(moments.getByText(/interest in .budget app. is up 2.4/i)).toBeVisible()
  await moments.getByRole('button', { name: /dismiss this alert/i }).click()
  await expect(moments).toHaveCount(0)
  await expect.poll(() => dismissed).toBe(true)
})

test('playbooks page lists what works per industry', async ({ page }) => {
  await signIn(page)
  await page.route('**/rest/v1/playbooks?*', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
    { domain_category: 'finance_fintech', generated_at: '2026-10-23T10:00:00Z',
      content: { headline: 'Humour beats urgency here.', do: ['Lead with a joke'], avoid: ['Countdown pressure'], audience: ['Freelancers'], next_test: 'Try testimonials.' },
      stats: { rounds: 4, campaigns: 2, overall_mean: 0.3, tones: [{ name: 'humorous', mean: 0.5, n: 2 }], styles: [{ name: 'minimalist', mean: 0.4, n: 3 }] } },
  ]) }))
  await page.goto('/playbooks')
  await expect(page.getByRole('heading', { name: 'Humour beats urgency here.' })).toBeVisible()
  await expect(page.getByText('Lead with a joke')).toBeVisible()
  await expect(page.getByText(/best so far: humorous copy with minimalist visuals/i)).toBeVisible()
})

test('an empty playbooks page explains how they appear', async ({ page }) => {
  await signIn(page)
  await page.goto('/playbooks')
  await expect(page.getByRole('heading', { name: /no playbooks yet/i })).toBeVisible()
})
