import type { CSSProperties, PointerEvent as ReactPointerEvent } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import PublicFooter from '../components/PublicFooter'
import Photo from '../components/Photo'
import PublicNav from '../components/PublicNav'
import { PHOTOS } from '../lib/photos'
import { useAuthTargets } from '../lib/site'
import styles from './Landing.module.css'

const LOOP_STEPS = [
  {
    title: 'Idea and product',
    desc: 'You describe the product and who it’s for, and add a photo of it. The idea is classified into its market by a fine-tuned model.',
  },
  {
    title: 'Feasibility',
    desc: "Google Trends, news volume and Bluesky and Mastodon conversation, queried in the campaign's own language, become a 0–100 score with its evidence shown.",
  },
  {
    title: 'Personas',
    desc: 'Ideal-customer personas grounded in that research, and a suggested email audience from your own subscribers.',
  },
  {
    title: 'Decide',
    desc: 'The decision engine recommends launch, test small, wait or kill, and blocks prohibited products and broken links outright.',
  },
  {
    title: 'Gate 1: the idea',
    desc: 'You approve, correct or reject before a word of creative is written, and choose who gets the email.',
  },
  {
    title: 'Creative',
    desc: 'A contextual bandit picks the style and tone. Your real product photo is set into one of 34 layouts, and the copy is written to match.',
  },
  {
    title: 'Crash test',
    desc: 'Rule checks for invented testimonials and false urgency, a simulated persona panel, and eight hostile scenarios, with a fixed version ready.',
  },
  {
    title: 'Gate 2: the ad',
    desc: 'You see the finished ad and every warning, edit the copy if you like, and approve what goes out.',
  },
  {
    title: 'Launch',
    desc: 'Posts to Bluesky, Mastodon and Reddit, and email to the next batch of your own subscribers, from your own address.',
  },
  {
    title: 'Measure and learn',
    desc: 'Clicks and conversions feed the bandit, a holdout proves real impact, fatigue and safety are watched, and the next round improves.',
  },
]

const MARQUEE_TOP = ['Bluesky', 'Mastodon', 'Email from your own domain', 'Google Trends', 'NewsAPI', 'FLUX', 'Groq', 'Gemini', 'Stripe']
const MARQUEE_BOTTOM = ['LangGraph', 'Supabase', 'Postgres RLS', 'Vault', 'pgvector', 'LinUCB bandit', 'Qwen2.5 + LoRA', 'GitHub Actions', 'MCP']

const STATS = [
  { value: 96, suffix: '%', label: 'agreement with hand-labelled launch decisions' },
  { value: 34, suffix: '', label: 'ad layouts, from a study of 128 real ads' },
  { value: 2, suffix: '', label: 'human gates before anything goes live' },
  { value: 86, suffix: '%', label: 'of ads follow your brand’s lessons with memory on' },
]

const DIFFERENTIATORS = [
  {
    kicker: '01 · Decide',
    title: 'It decides before it spends',
    body: 'Every campaign starts with a recommendation: launch, test small, wait or kill. Each piece of evidence shows its source and how fresh it is, and a prohibited product never gets an ad.',
  },
  {
    kicker: '02 · Prove',
    title: 'It proves what it caused',
    body: 'A randomized holdout gets nothing, so the lift you see is the lift the campaign caused, with a 95% interval. When the evidence is thin, it says so instead of guessing.',
  },
  {
    kicker: '03 · Protect',
    title: 'Safe by construction',
    body: 'Two human gates, a crash test before launch, a circuit breaker after it, and email only to people who opted in. Policy beats the model every time.',
  },
]

// One photo per differentiator, in the same order: signal, learning, control.
const DIFFERENTIATOR_ART = [PHOTOS.signal, PHOTOS.strategy, PHOTOS.review]

// Every capability, each linking to how it works in the docs. The first is the spotlight (spans two columns).
const FEATURES = [
  { id: 'decision', kicker: 'Decision engine', title: 'Launch, test small, wait or kill',
    body: 'Demand, momentum, purchase intent, competition, reach and track record, weighed with their sources shown. It agrees with hand-labelled scenarios 96% of the time and never launches a blocked idea.' },
  { id: 'creative', kicker: 'Product-first ads', title: 'Your real product, never repainted',
    body: 'Your photo is cut out and set into one of 34 layouts drawn from real ads.' },
  { id: 'crash-test', kicker: 'Crash test', title: 'Find the failure before launch',
    body: 'Invented testimonials, false urgency and claims you never made are caught, with a fix to approve.' },
  { id: 'loop', kicker: 'Learning loop', title: 'Every round leans on what worked',
    body: 'A contextual bandit over 20 styles and tones, rewarded by real clicks.' },
  { id: 'email', kicker: 'Email engine', title: 'Your customers, legally',
    body: 'Your own Resend account, opted-in contacts, a sign-up form, one email per person, unsubscribe built in.' },
  { id: 'impact', kicker: 'Proof of impact', title: 'Caused, not just correlated',
    body: 'A randomized holdout measures the lift your campaign really caused.' },
  { id: 'memory', kicker: 'Brand memory', title: 'It remembers why you decided',
    body: 'Reasons behind your edits become lessons the next campaign follows.' },
  { id: 'competitors', kicker: 'Competitor intelligence', title: 'Their moves, with sources',
    body: 'Offers, launches and messaging from approved public sources, with a response to weigh.' },
  { id: 'fatigue', kicker: 'Creative fatigue', title: 'Know when an ad wears out',
    body: 'A sustained drop is caught, and a refresh is proposed and measured.' },
  { id: 'safety', kicker: 'Circuit breaker', title: 'Pauses itself when unsafe',
    body: 'An ended offer, a dead link or bad news stops every send at once.' },
  { id: 'teams', kicker: 'Teams', title: 'Approvals that reach the right people',
    body: 'Roles, multi-approver gates and notifications in the app, by email and on Slack.' },
]

const PROOF = [
  { kicker: 'Channels', text: 'Real posts to Bluesky and Mastodon, and real email through each brand’s own Resend account.', wide: true },
  { kicker: 'Security', text: 'Row-level security on every table, and API keys kept in Supabase Vault.' },
  { kicker: 'Privacy', text: 'The AI never sees a contact’s address or name: only group names and counts.' },
  { kicker: 'Autonomy', text: 'Checkpointed in Postgres, so a campaign survives across GitHub Actions runs that share nothing else.', wide: true },
  { kicker: 'Evals', text: 'A golden set, an LLM judge and fixed benchmarks for every engine run in CI.' },
  { kicker: 'Learning', text: 'A contextual bandit learns from real clicks, and a fine-tuned classifier retrains weekly on your corrections.', wide: true },
]

// Pricing has two independent factors: who runs the AI (compute) and where
// the campaign goes (channels). The monthly total is the compute tier plus each
// paid channel picked. Prices are estimates; billing for them isn't built yet.
const COMPUTE_TIERS = [
  {
    id: 'free',
    tier: 'Free',
    name: 'Runs on us',
    price: 0,
    desc: 'The full loop on our free-tier models.',
    feats: ['3 rounds per campaign', '3 campaigns a day, 5 team members', '1,000 contacts for email'],
  },
  {
    id: 'byok',
    tier: 'Bring your own key',
    name: 'Your key, our loop',
    price: 9,
    desc: 'Your own model provider does the work. We charge a platform fee; the provider bills you for usage.',
    feats: ['10 rounds per campaign', 'Key kept in Supabase Vault', 'Model spend stays on your account'],
  },
  {
    id: 'paid',
    tier: 'Paid models',
    name: 'Premium models, managed',
    price: 29,
    desc: 'Sharper paid models for text and images, run and paid for by us.',
    feats: ['10 rounds per campaign', '50 campaigns a day, 50 members', 'Unlimited contacts'],
    featured: true,
  },
] as const

type ComputeId = (typeof COMPUTE_TIERS)[number]['id']

const FREE_CHANNELS = ['Bluesky', 'Mastodon', 'Gmail and other inboxes']
const PAID_CHANNELS = ['Google Ads', 'Meta Ads', 'Instagram', 'Facebook', 'LinkedIn', 'YouTube']
const PAID_CHANNEL_PRICE = 19 // per channel, per month; ad spend is billed by the network

const usd = (n: number) => `$${n}`

const FAQS = [
  {
    q: 'Does it really post and send?',
    a: 'Yes. Campaigns post to Bluesky and Mastodon and send email. A dry-run mode logs what would have gone out instead, and nothing is sent before you approve Gate 2.',
  },
  {
    q: 'Who does the email go to?',
    a: 'Only your own customers and subscribers who opted in: people you import with a consent record, or who confirm through your sign-up form. It goes from your own Resend account and address. CampaignIQ never finds, scrapes or buys addresses.',
  },
  {
    q: 'What does the AI see of my contacts?',
    a: 'Never an address or a name. To suggest who should get an email, it sees only group names and counts, such as "coffee: 180 people".',
  },
  {
    q: 'How are my keys stored?',
    a: 'Model-provider keys and your Resend key are kept in Supabase Vault and only the background workers can read them. For Resend, your full-access key is used once to set things up and then thrown away; only a sending-only key is kept.',
  },
  {
    q: 'What does the free plan include?',
    a: 'Everything: decision, personas, creative, crash test, both gates, distribution, email and measurement, for up to 3 rounds per campaign, 3 campaigns a day and 1,000 contacts.',
  },
  {
    q: 'Why isn’t Reddit on by default?',
    a: 'Reddit’s API access is restricted. The code is in place behind a switch for when access is available.',
  },
]

const HERO_LINES = [['One', 'idea', 'in.'], ['A', 'campaign', 'that'], ['proves', 'it', 'worked.']]

const ArrowIcon = () => (
  <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

function clamp01(n: number) {
  return Math.min(1, Math.max(0, n))
}

// Cursor-following glow for [data-spot] cards; one delegated handler for the page.
function trackSpotlight(e: ReactPointerEvent<HTMLDivElement>) {
  const card = (e.target as HTMLElement).closest<HTMLElement>('[data-spot]')
  if (!card) return
  const rect = card.getBoundingClientRect()
  card.style.setProperty('--mx', `${e.clientX - rect.left}px`)
  card.style.setProperty('--my', `${e.clientY - rect.top}px`)
}

export default function Landing() {
  const navigate = useNavigate()
  const pageRef = useRef<HTMLDivElement>(null)
  const heroMediaRef = useRef<HTMLDivElement>(null)
  const [heroIn, setHeroIn] = useState(false)
  const [activeStep, setActiveStep] = useState(0)
  const [openFaq, setOpenFaq] = useState<number | null>(0)
  const [compute, setCompute] = useState<ComputeId>('free')
  const [paidChannels, setPaidChannels] = useState<string[]>([])
  const computeTier = COMPUTE_TIERS.find((c) => c.id === compute)!
  const monthly = computeTier.price + paidChannels.length * PAID_CHANNEL_PRICE
  const toggleChannel = (name: string) =>
    setPaidChannels((on) => (on.includes(name) ? on.filter((c) => c !== name) : PAID_CHANNELS.filter((c) => on.includes(c) || c === name)))

  // Logged-in visitors can still read this page; its sign-up buttons just
  // take them straight to the app instead.
  const { signupTo } = useAuthTargets()

  // Section links from other pages (e.g. /#pricing) land here; glide to the
  // section once it has rendered. Auth errors are handled just below.
  const location = useLocation()
  useEffect(() => {
    const id = location.hash.slice(1)
    if (!id || id.includes('error=')) return
    const raf = requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' }))
    return () => cancelAnimationFrame(raf)
  }, [location.hash])

  // A failed email link redirects here (the Supabase Site URL); show the
  // error on the login page instead of silently dropping it.
  useEffect(() => {
    if (window.location.hash.includes('error=')) navigate('/login' + window.location.hash, { replace: true })
  }, [navigate])

  // Hero headline: words rise in once the first frame has painted.
  useEffect(() => {
    const id = requestAnimationFrame(() => setHeroIn(true))
    return () => cancelAnimationFrame(id)
  }, [])

  // Reveals and count-ups, both triggered the first time an element is seen.
  useEffect(() => {
    const page = pageRef.current
    if (!page) return
    const revealEls = Array.from(page.querySelectorAll<HTMLElement>('[data-reveal]'))
    const countEls = Array.from(page.querySelectorAll<HTMLElement>('[data-count]'))
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    function countUp(el: HTMLElement) {
      const target = Number(el.dataset.count)
      if (reduced) {
        el.textContent = String(target)
        return
      }
      const start = performance.now()
      const tick = (now: number) => {
        const p = clamp01((now - start) / 1400)
        el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))))
        if (p < 1) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }

    if (!('IntersectionObserver' in window)) {
      revealEls.forEach((el) => el.classList.add(styles.in))
      countEls.forEach(countUp)
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return
          const el = entry.target as HTMLElement
          if (el.dataset.count !== undefined) countUp(el)
          else el.classList.add(styles.in)
          io.unobserve(el)
        })
      },
      { threshold: 0.15, rootMargin: '0px 0px -8% 0px' },
    )
    revealEls.forEach((el) => io.observe(el))
    countEls.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])

  // Everything scroll-driven, in one rAF-throttled listener: hero media scale, the sticky loop's active step, and the stacking cards.
  useEffect(() => {
    const page = pageRef.current
    if (!page) return
    const media = heroMediaRef.current
    const steps = Array.from(page.querySelectorAll<HTMLElement>('[data-step]'))
    const stack = Array.from(page.querySelectorAll<HTMLElement>('[data-stack]'))
    let ticking = false

    function update() {
      const vh = window.innerHeight

      if (media) {
        const p = clamp01((vh - media.getBoundingClientRect().top) / (vh * 0.9))
        media.style.setProperty('--p', p.toFixed(3))
      }

      let current = 0
      steps.forEach((el, i) => {
        if (el.getBoundingClientRect().top < vh * 0.55) current = i
      })
      setActiveStep(current)

      // Each card shrinks and dims as the next one slides over it.
      stack.forEach((card, i) => {
        const next = stack[i + 1]
        const cover = next ? clamp01(1 - (next.getBoundingClientRect().top - card.getBoundingClientRect().top) / (vh * 0.7)) : 0
        card.style.setProperty('--cover', cover.toFixed(3))
      })
    }

    function onScroll() {
      if (ticking) return
      ticking = true
      requestAnimationFrame(() => {
        update()
        ticking = false
      })
    }

    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
    }
  }, [])

  let wordIndex = 0

  return (
    <div className={styles.page} ref={pageRef} onPointerMove={trackSpotlight}>
      <PublicNav />

      <main id="top">
        {/* Hero */}
        <section className={styles.hero}>
          <div className={styles.heroGlow} aria-hidden="true" />
          <div className={styles.wrap}>
            <h1 className={`${styles.heroTitle} ${heroIn ? styles.heroIn : ''}`}>
              {HERO_LINES.map((line, li) => (
                <span className={styles.heroLine} key={li}>
                  {line.map((word) => {
                    const i = wordIndex++
                    const accent = word === 'worked.'
                    return (
                      <span className={styles.wordMask} key={word}>
                        <span className={`${styles.word} ${accent ? styles.wordAccent : ''}`} style={{ '--i': i } as CSSProperties}>
                          {word}
                        </span>
                      </span>
                    )
                  })}
                </span>
              ))}
            </h1>
            <p className={`${styles.heroSub} ${heroIn ? styles.in : ''} ${styles.fadeUp}`} style={{ '--d': '0.55s' } as CSSProperties}>
              CampaignIQ decides whether a campaign should run, builds the ad around your real product, stress-tests it,
              launches it to social and to your own subscribers, and proves what it caused. You approve every step that matters.
            </p>
            <div className={`${styles.heroCtas} ${heroIn ? styles.in : ''} ${styles.fadeUp}`} style={{ '--d': '0.7s' } as CSSProperties}>
              <Link className={`${styles.btn} ${styles.btnPrimary}`} to={signupTo}>
                Start a campaign
                <ArrowIcon />
              </Link>
              <a className={`${styles.btn} ${styles.btnGhost}`} href="#loop">
                See how it runs
              </a>
            </div>
          </div>

          <div className={styles.heroMediaWrap}>
            <div className={styles.heroMedia} ref={heroMediaRef}>
              {/* 17 s looping simulation of one campaign round (animated WebP, rendered
                  from frontend/scripts/render_demo.py). Reduced-motion visitors get the still poster. */}
              <picture className={styles.demo}>
                <source media="(prefers-reduced-motion: reduce)" srcSet="/media/demo-loop-poster.webp" />
                <img
                  src="/media/demo-loop.webp"
                  width={1280}
                  height={720}
                  alt="Simulation of a CampaignIQ campaign: an idea is scored for feasibility, personas are generated, the creative is approved at Gate 2, published to Bluesky and email, and reward climbs across rounds"
                  decoding="async"
                />
              </picture>
            </div>
          </div>
        </section>

        {/* Marquee */}
        <section className={styles.marqueeSection} aria-label="Channels and stack">
          <p className={styles.marqueeLabel}>Real channels, real infrastructure</p>
          {[MARQUEE_TOP, MARQUEE_BOTTOM].map((row, r) => (
            <div className={styles.marqueeViewport} key={r}>
              <div className={`${styles.marqueeTrack} ${r === 1 ? styles.marqueeReverse : ''}`}>
                {[...row, ...row].map((item, i) => (
                  <span className={styles.marqueeItem} key={i} aria-hidden={i >= row.length}>
                    <span className={styles.marqueeDot} />
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </section>

        {/* Stats */}
        <section className={styles.statsSection}>
          <div className={`${styles.wrap} ${styles.statsGrid}`}>
            {STATS.map((s, i) => (
              <div className={`${styles.stat} ${styles.reveal}`} data-reveal key={s.label} style={{ '--i': i } as CSSProperties}>
                <div className={styles.statValue}>
                  <span data-count={s.value}>0</span>
                  {s.suffix}
                </div>
                <div className={styles.statLabel}>{s.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Sticky loop */}
        <section className={styles.loopSection} id="loop">
          <div className={`${styles.wrap} ${styles.loopGrid}`}>
            <div className={styles.loopSticky}>
              <span className={styles.eyebrow}>How it actually runs</span>
              <h2 className={styles.sectionTitle}>Ten steps. Two of them are yours.</h2>
              <p className={styles.sectionSub}>
                Every campaign is a LangGraph state machine, checkpointed in Postgres, that pauses at each human gate and
                resumes the moment you decide.
              </p>
              <div className={styles.loopCounter} aria-live="polite">
                <span className={styles.loopNum}>{String(activeStep + 1).padStart(2, '0')}</span>
                <span className={styles.loopOf}>/ {String(LOOP_STEPS.length).padStart(2, '0')}</span>
              </div>
              <div className={styles.loopTitleNow}>{LOOP_STEPS[activeStep].title}</div>
              <div className={styles.progress}>
                <span style={{ width: `${((activeStep + 1) / LOOP_STEPS.length) * 100}%` }} />
              </div>
            </div>
            <ol className={styles.loopList}>
              {LOOP_STEPS.map((step, i) => (
                <li
                  key={step.title}
                  data-step
                  className={`${styles.loopCard} ${i === activeStep ? styles.loopCardActive : ''} ${i < activeStep ? styles.loopCardDone : ''}`}
                >
                  <span className={styles.loopCardNum}>{String(i + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{step.title}</h3>
                    <p>{step.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Every capability */}
        <section className={styles.featureSection} id="features">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>What’s inside</span>
              <h2 className={styles.sectionTitle}>Everything a campaign needs, in one loop.</h2>
            </div>
            <div className={styles.featureGrid}>
              {FEATURES.map((f, i) => (
                <Link
                  key={f.id}
                  to={`/docs#${f.id}`}
                  data-spot
                  data-reveal
                  className={`${styles.featureTile} ${i === 0 ? styles.featureSpotlight : ''} ${styles.reveal}`}
                  style={{ '--i': i % 6 } as CSSProperties}
                >
                  <span className={styles.featureKicker}>{f.kicker}</span>
                  <h3>{f.title}</h3>
                  <p>{f.body}</p>
                  <span className={styles.featureMore}>
                    How it works
                    <ArrowIcon />
                  </span>
                </Link>
              ))}
            </div>
          </div>
        </section>

        {/* Stacking differentiators */}
        <section className={styles.stackSection} id="why">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>Why it isn’t a wrapper</span>
              <h2 className={styles.sectionTitle}>Three things most AI marketing tools skip.</h2>
            </div>
            <div className={styles.stack}>
              {DIFFERENTIATORS.map((d, i) => (
                <article className={styles.stackCard} data-stack key={d.title} style={{ '--i': i } as CSSProperties}>
                  <div className={styles.stackInner}>
                    <div className={styles.stackCopy}>
                      <span className={styles.stackKicker}>{d.kicker}</span>
                      <h3>{d.title}</h3>
                      <p>{d.body}</p>
                    </div>
                    <div className={styles.stackArt}>
                      <Photo photo={DIFFERENTIATOR_ART[i]} />
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </div>
        </section>

        {/* Bento proof */}
        <section className={styles.proofSection} id="proof">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>Not simulated</span>
              <h2 className={styles.sectionTitle}>Real channels, real data, real safeguards.</h2>
            </div>
            <div className={styles.bento}>
              {PROOF.map((p, i) => (
                <div
                  key={p.kicker}
                  data-spot
                  data-reveal
                  className={`${styles.bentoTile} ${p.wide ? styles.bentoWide : ''} ${styles.reveal}`}
                  style={{ '--i': i } as CSSProperties}
                >
                  <span className={styles.bentoKicker}>{p.kicker}</span>
                  <p>{p.text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section className={styles.pricingSection} id="pricing">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.center} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>Pricing</span>
              <h2 className={styles.sectionTitle}>Start free. Grow when it pays off.</h2>
              <p className={styles.sectionSub}>
                Your price is two choices: who runs the AI, and where your campaigns go. Every plan runs the same loop with every capability.
              </p>
            </div>
            <div className={`${styles.factorHead} ${styles.reveal}`} data-reveal>
              <span className={styles.factorNum}>01</span>
              <div>
                <h3>Compute</h3>
                <p>Who runs the AI.</p>
              </div>
            </div>
            <div className={styles.pricingGrid}>
              {COMPUTE_TIERS.map((t, i) => (
                <div
                  key={t.id}
                  data-spot
                  data-reveal
                  className={`${styles.priceCard} ${'featured' in t ? styles.priceFeatured : ''} ${styles.reveal}`}
                  style={{ '--i': i } as CSSProperties}
                >
                  {'featured' in t && <span className={styles.priceFlag}>For teams</span>}
                  <span className={styles.priceTier}>{t.tier}</span>
                  <div className={styles.priceName}>{t.name}</div>
                  <div className={styles.priceAmount}>
                    {usd(t.price)}
                    <span>{t.id === 'byok' ? '/ month platform fee' : '/ month'}</span>
                  </div>
                  <p className={styles.priceDesc}>{t.desc}</p>
                  <ul className={styles.priceFeats}>
                    {t.feats.map((f) => (
                      <li key={f}>
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        {f}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <div className={`${styles.factorHead} ${styles.reveal}`} data-reveal>
              <span className={styles.factorNum}>02</span>
              <div>
                <h3>Channels</h3>
                <p>Where the campaign goes.</p>
              </div>
            </div>
            <div className={styles.channelGrid}>
              <div data-spot data-reveal className={`${styles.priceCard} ${styles.reveal}`}>
                <span className={styles.priceTier}>Free channels</span>
                <div className={styles.priceName}>Post and email</div>
                <div className={styles.priceAmount}>
                  {usd(0)}
                  <span>/ month</span>
                </div>
                <p className={styles.priceDesc}>Organic posts, and email to your own opted-in subscribers.</p>
                <div className={styles.channelChips}>
                  {FREE_CHANNELS.map((c) => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
              </div>
              <div data-spot data-reveal className={`${styles.priceCard} ${styles.reveal}`} style={{ '--i': 1 } as CSSProperties}>
                <span className={styles.priceFlag}>Coming soon</span>
                <span className={styles.priceTier}>Paid channels</span>
                <div className={styles.priceName}>Ads on the big networks</div>
                <div className={styles.priceAmount}>
                  {usd(PAID_CHANNEL_PRICE)}
                  <span>/ month per channel</span>
                </div>
                <p className={styles.priceDesc}>Paid placements, through the same two gates and crash test. Ad spend is billed by the network.</p>
                <div className={styles.channelChips}>
                  {PAID_CHANNELS.map((c) => (
                    <span key={c}>{c}</span>
                  ))}
                </div>
              </div>
            </div>

            <div className={`${styles.estimator} ${styles.reveal}`} data-reveal>
              <div className={styles.estimatorPick}>
                <h3>Estimate your monthly price</h3>
                <fieldset>
                  <legend>Compute</legend>
                  <div className={styles.estimatorOptions}>
                    {COMPUTE_TIERS.map((t) => (
                      <label key={t.id} className={`${styles.estimatorOption} ${compute === t.id ? styles.estimatorOn : ''}`}>
                        <input type="radio" name="compute" value={t.id} checked={compute === t.id} onChange={() => setCompute(t.id)} />
                        {t.tier}
                        <span>{usd(t.price)}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
                <fieldset>
                  <legend>Paid channels</legend>
                  <div className={styles.estimatorOptions}>
                    {PAID_CHANNELS.map((c) => (
                      <label key={c} className={`${styles.estimatorOption} ${paidChannels.includes(c) ? styles.estimatorOn : ''}`}>
                        <input type="checkbox" checked={paidChannels.includes(c)} onChange={() => toggleChannel(c)} />
                        {c}
                        <span>+{usd(PAID_CHANNEL_PRICE)}</span>
                      </label>
                    ))}
                  </div>
                  <p className={styles.estimatorNote}>Bluesky, Mastodon and email are always included at no cost.</p>
                </fieldset>
              </div>
              <div className={styles.estimatorTotal} aria-live="polite">
                <span className={styles.priceTier}>Estimated total</span>
                <div className={styles.estimatorAmount}>
                  {usd(monthly)}
                  <span>/ month</span>
                </div>
                <ul>
                  <li>
                    <span>{computeTier.tier}</span>
                    <span>{usd(computeTier.price)}</span>
                  </li>
                  <li>
                    <span>Free channels</span>
                    <span>{usd(0)}</span>
                  </li>
                  {paidChannels.map((c) => (
                    <li key={c}>
                      <span>{c}</span>
                      <span>{usd(PAID_CHANNEL_PRICE)}</span>
                    </li>
                  ))}
                </ul>
                <p className={styles.estimatorNote}>
                  Estimated prices.{compute === 'byok' ? ' Model usage is billed by your provider.' : ''}
                  {paidChannels.length ? ' Ad spend is paid to each network and isn’t included.' : ''}
                </p>
                <Link className={`${styles.btn} ${styles.btnPrimary} ${styles.btnBlock}`} to={signupTo}>
                  {monthly === 0 ? 'Start free' : 'Get started'}
                  <ArrowIcon />
                </Link>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section className={styles.faqSection} id="faq">
          <div className={`${styles.wrap} ${styles.faqGrid}`}>
            <div className={`${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>FAQ</span>
              <h2 className={styles.sectionTitle}>Questions, answered plainly.</h2>
            </div>
            <div className={styles.faqList}>
              {FAQS.map((f, i) => {
                const open = openFaq === i
                return (
                  <div className={`${styles.faqItem} ${open ? styles.faqOpen : ''}`} key={f.q}>
                    <button className={styles.faqQ} aria-expanded={open} onClick={() => setOpenFaq(open ? null : i)}>
                      {f.q}
                      <span className={styles.faqIcon} aria-hidden="true" />
                    </button>
                    <div className={styles.faqA}>
                      <div>
                        <p>{f.a}</p>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className={styles.ctaSection}>
          <div className={`${styles.wrap}`}>
            <div className={`${styles.ctaCard} ${styles.reveal}`} data-reveal>
              <div className={styles.ctaGlow} aria-hidden="true" />
              <h2>Ready for a campaign that proves itself?</h2>
              <p>Describe one product. Approve two gates. See what it caused.</p>
              <Link className={`${styles.btn} ${styles.btnPrimary}`} to={signupTo}>
                Start a campaign
                <ArrowIcon />
              </Link>
            </div>
          </div>
        </section>
      </main>

      <PublicFooter />
    </div>
  )
}
