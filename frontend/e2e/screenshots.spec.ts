import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, type Page } from '@playwright/test'

// README screenshots (docs/screenshots), from the real built app against a
// mocked backend with realistic demo data. Not part of the normal run:
//   SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts --project=desktop
// The ad shown is a saved fixture (a real Tools run, benefit_checklist layout, with
// an unbranded bottle): taking screenshots never spends image generation.

test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to refresh the README screenshots')

const here = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(here, '../../docs/screenshots')
const AD = readFileSync(path.join(here, 'fixtures/drink-ad.jpg'))

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Piyo Drinks', personal: false }
const now = new Date().toISOString()
const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

const campaign = (id: string, status: string, idea: string, domain: string, score: number, created: string) => ({
  id, org_id: ORG.id, idea, domain_category: domain, feasibility_score: score,
  feasibility_rationale: 'Searches for electrolyte drinks climb every summer in India, and runners and delivery riders on Bluesky trade tips on staying hydrated in the heat.',
  status, current_round: 1, reddit_subreddit: null, email_to: ['team@piyo.example'], cta_url: 'https://piyo.example/shop',
  use_image_template: false, use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null,
  distributed_at: null, stop_requested: false, target_language: 'en', created_at: created, updated_at: created, ab_test: false, ab_decision: null,
  product_tagline: id === 'c1' ? 'Piyo aur pine do' : null,
})
const CAMPAIGNS = [
  campaign('c1', 'awaiting_gate_2', 'A new cold drink with electrolytes and minerals', 'food_beverage', 81, day(0)),
  campaign('c2', 'awaiting_metrics', 'Sugar-free lemon-mint electrolyte sachets for gym bags', 'food_beverage', 69, day(2)),
  campaign('c3', 'completed', 'Monsoon launch: ginger-lime hydration drink', 'food_beverage', 72, day(6)),
]
const PERSONAS = [
  { id: 'p1', campaign_id: 'c1', name: 'Priya, the weekend runner', demographics: '28, marketing analyst, runs 10 km every Sunday', psychographics: 'Tracks every run, reads labels, hates sugary sports drinks', channel_fit: 'bluesky, email', messaging_angle: 'Minerals back in, without the sugar crash', is_primary: true, archetype: 'athlete', gender: 'female' },
  { id: 'p2', campaign_id: 'c1', name: 'Ravi, the delivery rider', demographics: '24, food-delivery rider, 9 hours on the road', psychographics: 'Out in the heat all day, buys drinks at roadside shops', channel_fit: 'bluesky', messaging_angle: 'Stay sharp through the afternoon heat', is_primary: false, archetype: 'tradesperson', gender: 'male' },
  { id: 'p3', campaign_id: 'c1', name: 'Karan, the college cricketer', demographics: '20, plays for his college team', psychographics: 'Budget-aware, trains in the afternoon sun', channel_fit: 'bluesky', messaging_angle: 'Cold, salty, and cheaper than a sports drink', is_primary: false, archetype: 'student', gender: 'male' },
]
const ITER = {
  id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1,
  copy_text: 'Great refreshment awaits: a cold burst of electrolytes and minerals that revives you instantly. Sip now and feel the boost. #PiyoAurPineDo',
  image_prompt: 'A cool, pale blue studio backdrop with soft light and empty space on the right for a drink bottle',
  image_path: 'c1/round-1.jpg', image_version: 0, headline: 'Instant Hydration with Electrolytes', cta: 'Drink Now',
  template: 'benefit_checklist',
  preflight_score: 82, preflight_passed: true, bluesky_post_uri: null, reddit_post_url: null, email_id: null,
  image_style: 'testimonial_social_proof', copy_tone: 'direct_factual', arm_index: 4,
  guardrail_flags: { issues: [], disclaimer: null },
  focus_group: {
    reactions: [
      { name: 'Priya, the weekend runner', archetype: 'athlete', gender: 'female', reaction: 'click', likelihood: 82, quote: 'If it really has no added sugar, this goes in my bag on Sunday.' },
      { name: 'Ravi, the delivery rider', archetype: 'tradesperson', gender: 'male', reaction: 'click', likelihood: 68, quote: 'By 3pm I need something cold that actually helps.' },
      { name: 'Karan, the college cricketer', archetype: 'student', gender: 'male', reaction: 'scroll', likelihood: 38, quote: 'Looks good, but what does it cost?' },
    ],
    verdict: { click: 2, scroll: 1, object: 0 },
    average_likelihood: 63,
  },
  arm_explain: {
    algorithm: 'LinUCB', alpha: 0.5,
    context: { age_bracket: '25-34', income_tier: 'mid', domain_category: 'food_beverage', channels: ['bluesky', 'email'] },
    chosen: { arm_index: 4, image_style: 'testimonial_social_proof', copy_tone: 'direct_factual', expected: 0.47, bonus: 0.1, score: 0.57, pulls: 6, mean_reward: 0.45 },
    mode: 'exploit', rank: 1,
    alternatives: [
      { arm_index: 19, image_style: 'lifestyle_aspirational', copy_tone: 'aspirational_emotional', expected: 0.31, bonus: 0.2, score: 0.51, pulls: 3, mean_reward: 0.3 },
      { arm_index: 0, image_style: 'minimalist', copy_tone: 'direct_factual', expected: 0.12, bonus: 0.33, score: 0.45, pulls: 1, mean_reward: 0.12 },
    ],
    arms_tried: 8, total_rounds: 24,
  },
}

function bodyFor(url: string): unknown {
  if (url.includes('/memberships')) return [{ role: 'owner', organizations: ORG }]
  if (url.includes('/rpc/org_usage'))
    return { plan: 'pro', limits: { campaigns_per_day: 20, active_campaigns: 10, members: 10, llm_tokens_per_day: 1500000 }, used: { campaigns_per_day: 1, active_campaigns: 2, members: 3, llm_tokens_per_day: 180000 } }
  if (url.includes('/rpc/org_members')) return [{ user_id: USER.id, email: USER.email, role: 'owner', username: 'ava' }]
  if (url.includes('/market_alerts'))
    return [{ id: 1, campaign_id: 'c1', kind: 'trend', created_at: now, campaigns: { idea: CAMPAIGNS[0].idea }, detail: { keyword: 'electrolyte drink', value: 78, baseline: 30, ratio: 2.6 } }]
  if (url.includes('/playbooks'))
    return [{
      domain_category: 'food_beverage', generated_at: now,
      content: {
        headline: 'Benefit checklists with plain, direct copy win for drink launches; urgency lost every time.',
        do: ['Name the benefit in the first five words', 'Show the bottle big, cold and front-on'],
        avoid: ['Countdown pressure and “last chance” language', 'Health claims the label can’t back up'],
        audience: ['Runners 25–34 click most on weekend mornings', 'Students respond to price, not ingredients'],
        next_test: 'Try a giant-word layout with the flavour name behind the bottle.',
      },
      stats: { rounds: 9, campaigns: 3, overall_mean: 0.39, tones: [{ name: 'direct_factual', mean: 0.48, n: 5 }, { name: 'urgency_scarcity', mean: 0.13, n: 2 }], styles: [{ name: 'testimonial_social_proof', mean: 0.5, n: 4 }, { name: 'minimalist', mean: 0.34, n: 3 }] },
    }]
  if (url.includes('/rpc/model_card'))
    return {
      versions: [
        { version: 'v2', revision: '0123456789abcdef', trained_at: day(3), base_model: 'Qwen2.5-1.5B-Instruct', method: 'LoRA fine-tune (rank 16, Unsloth), quantised to 4-bit GGUF; runs on CPU inside the workers', data: { synthetic_examples: 560, corrections_used: 41, labels: 12 }, metrics: { golden: 0.89, golden_n: 18, heldout: 0.79, heldout_n: 96, median_ms: 700, invalid_outputs: 0, top_confusions: [['food_beverage', 'ecommerce_retail', 7]] }, baseline_metrics: { label: 'Previous version', golden: 0.8333, heldout: 0.75 }, notes: 'Weekly retrain with reviewer corrections.' },
        { version: 'v1', revision: null, trained_at: day(14), base_model: 'Qwen2.5-1.5B-Instruct', method: 'LoRA', data: {}, metrics: { golden: 0.8333, heldout: 0.75 }, baseline_metrics: null, notes: null },
      ],
      deployment: { active_revision: '0123456789abcdef', candidate_revision: null, mode: 'shadow', canary_percent: 0, updated_at: now },
      shadow: { compared: 120, agreement: 0.93 },
      corrections: { total: 57, since_last_training: 16, last_30_days: 23 },
    }
  if (url.includes('/rpc/')) return null
  if (url.includes('/campaigns')) {
    // A campaign's own id, not org_id=eq.… on the list query.
    const id = /[?&]id=eq\.([^&]+)/.exec(url)?.[1]
    return id ? CAMPAIGNS.filter((c) => c.id === id) : CAMPAIGNS
  }
  if (url.includes('/iterations')) return [ITER]
  if (url.includes('/personas')) return PERSONAS
  if (url.includes('/gate_decisions')) return [{ id: 'g1', campaign_id: 'c1', gate_number: 2, round_number: 1, decision: null, decided_at: null }]
  if (url.includes('/brand_kits')) return [{ voice: 'Bright, plain-spoken, a little playful. Short sentences.', preferred_words: ['cold', 'refresh'], forbidden_words: ['cure', 'miracle'], required_phrase: '#PiyoAurPineDo', brand_color: '#2b2f8f', logo_path: null }]
  return []
}

async function demoSession(page: Page) {
  await page.route('**/rest/v1/**', async (route) => {
    const url = route.request().url()
    const single = (route.request().headers()['accept'] ?? '').includes('vnd.pgrst.object')
    let body = bodyFor(url)
    if (single) body = Array.isArray(body) ? (body[0] ?? null) : body
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.route('**/functions/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route('**/auth/v1/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...USER, aud: 'authenticated' }) }))
  await page.route('**/storage/v1/object/sign/**', (route) => {
    if (route.request().method() === 'POST') {
      const p = new URL(route.request().url()).pathname.split('/storage/v1')[1]
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ signedURL: `${p}?token=demo` }) })
    }
    return route.fulfill({ status: 200, contentType: 'image/jpeg', body: AD })
  })
  await page.route('**/personas/models/**', (route) => route.fulfill({ status: 404, body: '' }))
  await page.addInitScript((user) => {
    const t = Math.floor(Date.now() / 1000)
    localStorage.setItem('sb-127-auth-token', JSON.stringify({ access_token: 'e2e', refresh_token: 'e2e', token_type: 'bearer', expires_in: 3600, expires_at: t + 3600, user: { ...user, aud: 'authenticated', role: 'authenticated', user_metadata: { username: 'ava' }, app_metadata: {} } }))
  }, USER)
}

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 })

async function shoot(page: Page, route: string, file: string, ready: (p: Page) => Promise<unknown>, fullPage = false) {
  await demoSession(page)
  await page.goto(route)
  await ready(page)
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(800) // entrance animations settle
  await page.screenshot({ path: path.join(OUT, file), fullPage })
}

test('dashboard', async ({ page }) => {
  await shoot(page, '/dashboard', 'dashboard.png', (p) => p.getByText(CAMPAIGNS[0].idea).first().waitFor())
})

test('campaign at Gate 2', async ({ page }) => {
  await shoot(page, '/campaigns/c1', 'gate-2.png', (p) => p.getByRole('img', { name: /blue studio backdrop/i }).first().waitFor({ timeout: 15_000 }), true)
})

test('playbooks', async ({ page }) => {
  await shoot(page, '/playbooks', 'playbooks.png', (p) => p.getByText(/benefit checklists/i).first().waitFor())
})

test('model card', async ({ page }) => {
  await shoot(page, '/models', 'model-card.png', (p) => p.getByText(/qwen2\.5/i).first().waitFor())
})
