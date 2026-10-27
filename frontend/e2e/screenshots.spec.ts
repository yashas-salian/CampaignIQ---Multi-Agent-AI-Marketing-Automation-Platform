import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { test, type Page } from '@playwright/test'

// README screenshots (docs/screenshots), from the real built app against a
// mocked backend with realistic demo data. Not part of the normal run:
//   SCREENSHOTS=1 npx playwright test e2e/screenshots.spec.ts --project=desktop
// The ad shown is a saved fixture (a real campaign's round-1 ad, script_flank
// layout): taking screenshots never spends image generation.

test.skip(!process.env.SCREENSHOTS, 'Set SCREENSHOTS=1 to refresh the README screenshots')

const here = path.dirname(fileURLToPath(import.meta.url))
const OUT = path.resolve(here, '../../docs/screenshots')
const AD = readFileSync(path.join(here, 'fixtures/brewly-ad.jpg'))

const USER = { id: '11111111-1111-1111-1111-111111111111', email: 'ava@example.com' }
const ORG = { id: '22222222-2222-2222-2222-222222222222', name: 'Brewly', personal: false }
const now = new Date().toISOString()
const day = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString()

const campaign = (id: string, status: string, idea: string, domain: string, score: number, created: string) => ({
  id, org_id: ORG.id, idea, domain_category: domain, feasibility_score: score,
  feasibility_rationale: 'Ready-to-drink cold brew is a growing niche in Indian metros, and students and young professionals on Bluesky trade tips on staying sharp through late study and work nights.',
  status, current_round: 1, reddit_subreddit: null, email_to: ['team@brewly.example'], cta_url: 'https://brewly.example/cold-brew',
  use_image_template: false, use_email_template: false, max_rounds: 3, max_duration_minutes: null, campaign_summary: null,
  distributed_at: null, stop_requested: false, target_language: 'en', created_at: created, updated_at: created, ab_test: false, ab_decision: null,
  product_tagline: id === 'c1' ? 'Cold, smooth, ready when you are.' : null,
})
const CAMPAIGNS = [
  campaign('c1', 'awaiting_gate_2', 'Brewly Cold Brew Cans: ready-to-drink cold brew coffee for students and young professionals', 'food_beverage', 74, day(0)),
  campaign('c2', 'awaiting_metrics', 'Oat-milk cold brew concentrate for home offices', 'food_beverage', 66, day(2)),
  campaign('c3', 'completed', 'Monsoon launch: hazelnut iced latte cans', 'food_beverage', 71, day(6)),
]
const PERSONAS = [
  { id: 'p1', campaign_id: 'c1', name: 'Aarav Mehta', demographics: 'Male, 21, undergraduate engineering student, lives in Bengaluru', psychographics: 'Values convenience, loves tech, stays up late studying, seeks an affordable energy boost', channel_fit: 'Bluesky, campus groups, email', messaging_angle: 'Fuel your all-night study sessions with smooth, low-sugar cold brew', is_primary: true, archetype: 'student', gender: 'male' },
  { id: 'p2', campaign_id: 'c1', name: 'Priya Sharma', demographics: 'Female, 27, junior product manager, lives in Mumbai', psychographics: 'Career-driven, health-conscious, prefers ready-to-drink options', channel_fit: 'Bluesky, email', messaging_angle: 'Stay sharp at the office with clean energy and no crash', is_primary: false, archetype: 'professional', gender: 'female' },
  { id: 'p3', campaign_id: 'c1', name: 'Rohit Singh', demographics: 'Male, 29, freelance graphic designer, lives in Delhi', psychographics: 'Creative, irregular hours, works from co-working spaces', channel_fit: 'Bluesky, Mastodon', messaging_angle: 'A smooth, low-sugar cold brew that powers your design marathons', is_primary: false, archetype: 'designer', gender: 'male' },
]
const ITER = {
  id: 'i1', campaign_id: 'c1', round_number: 1, preflight_attempt: 1,
  copy_text: 'Need a brain boost for that all-night coding sprint? Grab a Brewly can: cold, smooth, and ready when you are. Great taste, zero hassle. #BrewlyCold',
  image_prompt: 'The real product photo as the hero, laid out as script words either side on bright rings, with the words: Smooth Energy in a Can; Cold, smooth, ready when you are.; Sip Now.',
  image_path: 'c1/round-1.jpg', image_version: 0, headline: 'Smooth Energy in a Can', cta: 'Sip Now',
  template: 'script_flank',
  preflight_score: 70, preflight_passed: true, bluesky_post_uri: null, reddit_post_url: null, email_id: null,
  image_style: 'humor_meme', copy_tone: 'humorous', arm_index: 10,
  guardrail_flags: { issues: [], disclaimer: null },
  focus_group: {
    reactions: [
      { name: 'Aarav Mehta', archetype: 'student', gender: 'male', reaction: 'click', likelihood: 72, quote: 'I need an affordable, low-sugar boost for my late-night coding, so I’d click to learn more.' },
      { name: 'Priya Sharma', archetype: 'professional', gender: 'female', reaction: 'scroll', likelihood: 48, quote: 'I prefer a premium, clean-energy drink, so I’d just scroll past this ad.' },
      { name: 'Rohit Singh', archetype: 'designer', gender: 'male', reaction: 'click', likelihood: 68, quote: 'A tasty, low-sugar cold brew sounds perfect for my design marathons, so I’d click.' },
    ],
    verdict: { click: 2, scroll: 1, object: 0 },
    average_likelihood: 63,
  },
  arm_explain: {
    algorithm: 'LinUCB', alpha: 0.5,
    context: { age_bracket: '18-24', income_tier: 'low', domain_category: 'food_beverage', channels: ['bluesky', 'email', 'mastodon'] },
    chosen: { arm_index: 10, image_style: 'humor_meme', copy_tone: 'humorous', expected: 0.099, bonus: 0.438, score: 0.538, pulls: 66, mean_reward: 0.865 },
    mode: 'explore', rank: 1,
    alternatives: [
      { arm_index: 0, image_style: 'minimalist', copy_tone: 'direct_factual', expected: 0, bonus: 0.5, score: 0.5, pulls: 0, mean_reward: null },
      { arm_index: 1, image_style: 'minimalist', copy_tone: 'urgency_scarcity', expected: 0, bonus: 0.5, score: 0.5, pulls: 0, mean_reward: null },
    ],
    arms_tried: 2, total_rounds: 131,
  },
}

function bodyFor(url: string): unknown {
  if (url.includes('/memberships')) return [{ role: 'owner', organizations: ORG }]
  if (url.includes('/rpc/org_usage'))
    return { plan: 'pro', limits: { campaigns_per_day: 20, active_campaigns: 10, members: 10, llm_tokens_per_day: 1500000 }, used: { campaigns_per_day: 1, active_campaigns: 2, members: 3, llm_tokens_per_day: 180000 } }
  if (url.includes('/rpc/org_members')) return [{ user_id: USER.id, email: USER.email, role: 'owner', username: 'ava' }]
  if (url.includes('/market_alerts'))
    return [{ id: 1, campaign_id: 'c1', kind: 'trend', created_at: now, campaigns: { idea: CAMPAIGNS[0].idea }, detail: { keyword: 'cold brew coffee', value: 72, baseline: 30, ratio: 2.4 } }]
  if (url.includes('/playbooks'))
    return [{
      domain_category: 'food_beverage', generated_at: now,
      content: {
        headline: 'Playful script layouts with light, humorous copy win for coffee launches; urgency lost every time.',
        do: ['Name the taste in the first five words', 'Show the can big, cold and tilted'],
        avoid: ['Countdown pressure and “last chance” language', 'Energy claims the label can’t back up'],
        audience: ['Students 18–24 click most late at night', 'Young professionals respond to clean energy, not price'],
        next_test: 'Try a giant-word layout with “COLD” behind the can.',
      },
      stats: { rounds: 9, campaigns: 3, overall_mean: 0.39, tones: [{ name: 'humorous', mean: 0.48, n: 5 }, { name: 'urgency_scarcity', mean: 0.13, n: 2 }], styles: [{ name: 'humor_meme', mean: 0.5, n: 4 }, { name: 'minimalist', mean: 0.34, n: 3 }] },
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
  if (url.includes('/brand_kits')) return [{ voice: 'Easy-going and a little cheeky. Short sentences.', preferred_words: ['smooth', 'cold'], forbidden_words: ['cure', 'miracle'], required_phrase: '#BrewlyCold', brand_color: '#2b2f8f', logo_path: null }]
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
  await shoot(page, '/campaigns/c1', 'gate-2.png', (p) => p.getByRole('img', { name: /script words either side/i }).first().waitFor({ timeout: 15_000 }), true)
})

test('playbooks', async ({ page }) => {
  await shoot(page, '/playbooks', 'playbooks.png', (p) => p.getByText(/playful script layouts/i).first().waitFor())
})

test('model card', async ({ page }) => {
  await shoot(page, '/models', 'model-card.png', (p) => p.getByText(/qwen2\.5/i).first().waitFor())
})
