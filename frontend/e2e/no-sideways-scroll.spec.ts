import { expect, test, type Page } from '@playwright/test'

// Every page must scroll vertically only, at phone through tablet widths.
// Signed-in pages run against a mocked backend filled with deliberately long
// content (URLs, emails, names) since that is what pushes layouts sideways.
// On failure the message lists the elements that stick out past the screen.
const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava.longname.example@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Personal', personal: true }
const now = new Date().toISOString()
const campaign = (id: string, status: string, idea: string) => ({
  id, org_id: ORG.id, idea, domain_category: 'finance_fintech', feasibility_score: 72, feasibility_rationale: 'Strong demand. '.repeat(20),
  status, current_round: 1, reddit_subreddit: null, email_to: ['someone.with.a.long.address@example.com'], cta_url: 'https://example.com/a/very/long/path/that/keeps/going/and/going',
  use_image_template: false, use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null,
  distributed_at: now, stop_requested: false, target_language: 'en', created_at: now, updated_at: now, ab_test: true,
})
const CAMPAIGNS = [
  campaign('c1', 'awaiting_gate_2', 'AI budgeting app for first-time freelancers who struggle with irregular income'),
  campaign('c2', 'awaiting_metrics', 'Supercalifragilisticexpialidociousmarketplaceforhandmadegoods'),
  campaign('c3', 'completed', 'Meal kit'),
]
const ITER = {
  id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1, copy_text: 'Sam, a graphic designer, says the app changed everything. https://example.com/a-really-long-link-without-breaks-abcdefghijklmnopqrstuvwxyz',
  image_prompt: 'prompt', preflight_score: 62, preflight_passed: true, bluesky_post_uri: 'at://did:plc:abcdefghijklmnop/app.bsky.feed.post/3kxyzabcdefg', reddit_post_url: null,
  email_id: 'email-id-1234567890', image_style: 'minimal', copy_tone: 'friendly', arm_index: 2, guardrail_flags: null, copy_text_b: 'Variant B copy', image_style_b: 'bold', copy_tone_b: 'urgent',
  focus_group: {
    reactions: [
      { name: 'Sam the freelance designer with a long name', archetype: 'designer', gender: 'female', reaction: 'click', likelihood: 78, quote: 'Finally something that gets irregular income; I would try it this week without a second thought.' },
      { name: 'Priya', archetype: 'doctor', gender: 'male', reaction: 'object', likelihood: 8, quote: 'Too pushy.' },
    ],
    verdict: { click: 1, scroll: 0, object: 1 },
    average_likelihood: 43,
  },
  arm_explain: {
    algorithm: 'LinUCB', alpha: 0.5,
    context: { age_bracket: '25-34', income_tier: 'mid', domain_category: 'finance_fintech', channels: ['bluesky', 'email'] },
    chosen: { arm_index: 9, image_style: 'testimonial_social_proof', copy_tone: 'aspirational_emotional', expected: 0.42, bonus: 0.12, score: 0.54, pulls: 7, mean_reward: 0.41 },
    mode: 'exploit', rank: 1,
    alternatives: [
      { arm_index: 3, image_style: 'minimalist', copy_tone: 'aspirational_emotional', expected: 0.1, bonus: 0.35, score: 0.45, pulls: 1, mean_reward: 0.1 },
      { arm_index: 14, image_style: 'urgency_scarcity', copy_tone: 'urgency_scarcity', expected: 0, bonus: 0.4, score: 0.4, pulls: 0, mean_reward: null },
    ],
    arms_tried: 6, total_rounds: 31,
  },
}
const PERSONA = (id: string, name: string) => ({ id, campaign_id: 'c1', name, demographics: '34, freelance designer in Pune', psychographics: 'Values flexibility', channel_fit: 'email, bluesky', messaging_angle: 'Save hours every month', is_primary: id === 'p1', archetype: 'designer' })
const METRICS = [
  { id: 'm1', campaign_id: 'c1', round_number: 1, channel: 'email', raw_metrics: { opens: 12, clicks: 3, sent: 40 }, reward: 0.4, collected_at: now },
  { id: 'm2', campaign_id: 'c1', round_number: 1, channel: 'bluesky', raw_metrics: { likes: 5, reposts: 1, replies: 0 }, reward: 0.2, collected_at: now },
]

function bodyFor(url: string): unknown {
  if (url.includes('/memberships')) return [{ role: 'owner', organizations: ORG }]
  if (url.includes('/rpc/org_usage')) return { plan: 'free', limits: { campaigns_per_day: 3, active_campaigns: 3, members: 5, llm_tokens_per_day: 150000 }, used: { campaigns_per_day: 1, active_campaigns: 2, members: 1, llm_tokens_per_day: 30000 } }
  if (url.includes('/rpc/is_platform_admin')) return true
  if (url.includes('/rpc/org_members')) return [{ user_id: USER.id, email: USER.email, role: 'owner', username: 'ava' }]
  if (url.includes('/rpc/admin_orgs')) return [{ id: 'o1', name: 'A very long organisation name that keeps going Ltd', plan: 'pro', personal: false, members: 12, campaigns: 340, tokens_24h: 1234567, owner_email: 'owner.with.a.long.email.address@example-company.com', created_at: now }]
  if (url.includes('/rpc/admin_dead_deliveries')) return [{ id: 'd9', campaign_id: '6aae4421-d40d-4038-97b6-dd1b543f0ccf', channel: 'email', round_number: 2, attempts: 5, last_error: 'HTTPSConnectionPool(host=api.resend.com, port=443): Max retries exceeded with url: /emails' }]
  if (url.includes('/rpc/admin_flags')) return [{ key: 'experimental_very_long_feature_flag_name', description: 'Something', enabled: true, rollout_percent: 50 }]
  if (url.includes('/rpc/llm_usage_stats')) return []
  if (url.includes('/rpc/model_card')) return {
    versions: [
      { version: 'v2', revision: '0123456789abcdef', trained_at: now, base_model: 'Qwen2.5-1.5B-Instruct', method: 'LoRA fine-tune (rank 16, Unsloth), quantised to 4-bit GGUF; runs on CPU inside the workers', data: { synthetic_examples: 560, corrections_used: 41, labels: 12 }, metrics: { golden: 0.89, golden_n: 18, heldout: 0.79, heldout_n: 96, median_ms: 700, invalid_outputs: 0, top_confusions: [['food_beverage', 'ecommerce_retail', 7], ['consumer_electronics', 'entertainment_media', 2]] }, baseline_metrics: { label: 'Previous version', golden: 0.8333, heldout: 0.75 }, notes: 'Weekly retrain.' },
      { version: 'v1', revision: null, trained_at: now, base_model: 'Qwen2.5-1.5B-Instruct', method: 'LoRA', data: {}, metrics: { golden: 0.8333, heldout: 0.75 }, baseline_metrics: null, notes: null },
    ],
    deployment: { active_revision: '0123456789abcdef', candidate_revision: 'fedcba9876543210', mode: 'canary', canary_percent: 10, updated_at: now },
    shadow: { compared: 120, agreement: 0.93 },
    corrections: { total: 57, since_last_training: 16, last_30_days: 23 },
  }
  if (url.includes('/rpc/')) return null
  if (url.includes('/capability_runs')) return [
    { id: 'r1', capability: 'personas', status: 'succeeded', params: { idea: 'AI budgeting app for first-time freelancers with irregular income' }, error: null, created_at: now,
      result: [PERSONA('p1', 'Sam the freelance designer'), PERSONA('p2', 'Priya'), PERSONA('p3', 'Leo')] },
    { id: 'r2', capability: 'feasibility', status: 'succeeded', params: { idea: 'Meal kit' }, error: null, created_at: now,
      result: { score: 72, rationale: 'Strong demand. '.repeat(10), signals: { trends: { keyword: 'meal kit delivery subscription', mean_interest: 55 } } } },
    { id: 'r3', capability: 'image', status: 'failed', params: { idea: 'x' }, error: 'OpenAI 401 Incorrect API key provided: sk-test-************************************abcd', created_at: now, result: null },
  ]
  if (url.includes('/api_keys')) return [{ id: 'k1', name: 'Production integration key for the CRM sync', prefix: 'mos_abcdef12', scopes: ['read', 'write'], created_at: now, last_used_at: now, revoked_at: null }]
  if (url.includes('/webhook_deliveries')) return [{ id: 1, event: 'campaign.status_changed', status: 'delivered', attempts: 1, response_status: 200, created_at: now }]
  if (url.includes('/webhooks')) return [{ id: 'w1', url: 'https://hooks.example.com/services/T000000/B000000/XXXXXXXXXXXXXXXXXXXXXXXX', secret: 'whsec_abcdef', events: ['campaign.', 'gate.vote', 'delivery.'], active: true }]
  if (url.includes('/provider_keys_masked')) return [{ capability: 'llm', provider: 'openai', masked_key: 'sk-proj-****************************************abcd', created_at: now }]
  if (url.includes('/audit_log')) return [{ id: 1, action: 'campaign.status_changed', actor: USER.id, target_type: 'campaign', target_id: '6aae4421-d40d-4038-97b6-dd1b543f0ccf', details: { from: 'awaiting_gate_1', to: 'awaiting_gate_2' }, created_at: now, hash: 'abc' }]
  if (url.includes('/campaigns')) {
    // A single-campaign read filters by id; returning every row would be a "multiple rows" error.
    const id = /id=eq\.([^&]+)/.exec(url)?.[1]
    return id ? CAMPAIGNS.filter((c) => c.id === id) : CAMPAIGNS
  }
  if (url.includes('/iterations')) return [ITER]
  if (url.includes('/personas')) return [PERSONA('p1', 'Sam the freelance designer'), PERSONA('p2', 'Priya'), PERSONA('p3', 'Leo')]
  if (url.includes('/metrics')) return METRICS
  if (url.includes('/deliveries')) return [{ id: 'd1', campaign_id: 'c1', channel: 'email', status: 'sent', created_at: now }]
  return []
}

async function signIn(page: Page) {
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body = bodyFor(url)
    if (single) body = Array.isArray(body) ? (body[0] ?? null) : body
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({ access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600, user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} } }))
  }, USER)
}

const ROUTES = ['/models', '/tools/history', '/dashboard', '/campaigns/c1', '/campaigns/c1/metrics', '/calendar', '/tools', '/settings', '/admin', '/', '/about', '/contact', '/privacy', '/terms', '/docs', '/status', '/login', '/signup', '/nope']
const WIDTHS = [320, 360, 390, 430, 768]

test('no page scrolls sideways on phones or tablets', async ({ browser }, info) => {
  test.skip(info.project.name !== 'desktop', 'sweeps its own viewport sizes')
  test.setTimeout(600_000)
  const lines: string[] = []
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({ viewport: { width, height: 800 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 })
    const page = await ctx.newPage()
    await signIn(page)
    for (const route of ROUTES) {
      await page.goto(route)
      await page.waitForLoadState('networkidle').catch(() => {})
      await page.waitForTimeout(700)
      const res = await page.evaluate(() => {
        const vw = document.documentElement.clientWidth
        const clipped = (el: Element) => {
          for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
            const s = getComputedStyle(p)
            if (/(hidden|auto|scroll|clip)/.test(s.overflowX)) {
              const r = p.getBoundingClientRect()
              if (r.right <= vw + 1 && r.left >= -1) return true
            }
          }
          return false
        }
        const name = (el: Element) => {
          const cls = typeof el.className === 'string' ? el.className.split(' ').filter(Boolean).map((c) => c.replace(/_[a-zA-Z0-9]{5}$/, '')).join('.') : ''
          return `${el.tagName.toLowerCase()}${cls ? '.' + cls : ''}`
        }
        const out: string[] = []
        const seen = new Set<string>()
        for (const el of Array.from(document.body.querySelectorAll('*'))) {
          const r = el.getBoundingClientRect()
          if (r.width === 0 || r.height === 0) continue
          if (r.right > vw + 1 || r.left < -1) {
            if (clipped(el)) continue
            const path: string[] = []
            for (let p: Element | null = el; p && p !== document.body && path.length < 4; p = p.parentElement) path.unshift(name(p))
            const key = path.join(' > ')
            if (seen.has(key)) continue
            seen.add(key)
            out.push(`${key}  [${Math.round(r.left)}..${Math.round(r.right)}]`)
          }
        }
        return { sw: document.documentElement.scrollWidth, vw, out: out.slice(0, 12), crashed: /something went wrong/i.test(document.body.innerText) }
      })
      const status = (res.sw > res.vw ? `SCROLLS +${res.sw - res.vw}` : 'ok') + (res.crashed ? ' CRASHED' : '')
      lines.push(`${width} ${route} ${status}${res.out.length ? '\n    ' + res.out.join('\n    ') : ''}`)
    }
    await ctx.close()
  }
  const bad = lines.filter((l) => / SCROLLS| CRASHED/.test(l))
  expect(bad, bad.join('\n')).toEqual([])
})
