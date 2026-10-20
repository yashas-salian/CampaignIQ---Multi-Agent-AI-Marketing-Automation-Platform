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
    title: 'Idea intake',
    desc: 'Classifies the idea into a fixed domain (fitness, B2B SaaS, food & beverage…), the same tag the bandit later uses as context.',
  },
  {
    title: 'Feasibility',
    desc: "Google Trends, NewsAPI and Bluesky/Mastodon search, queried in the campaign's own language, combine into a transparent 0–100 score with a written rationale.",
  },
  {
    title: 'Audience',
    desc: 'Generates ideal-customer personas grounded in that research. One primary persona drives the round.',
  },
  {
    title: 'Gate 1: the idea',
    desc: 'You approve, edit or reject before a single word of creative is written.',
  },
  {
    title: 'Creative',
    desc: 'A contextual bandit picks the style and tone archetype from real past engagement; copy and image are generated to match, novelty-checked against your own history.',
  },
  {
    title: 'Pre-flight',
    desc: 'A simulated persona panel reacts before anything real goes out, retrying up to three times and keeping the best attempt.',
  },
  {
    title: 'Gate 2: the creative',
    desc: 'A final approval before real posts and real sends.',
  },
  {
    title: 'Distribute',
    desc: "Real posts to Bluesky and real email via Resend, with clicks tracked through our own redirect rather than a third party's word for it.",
  },
  {
    title: 'Measure & learn',
    desc: "Engagement becomes the bandit's reward. The next round is rewritten from what actually happened, up to your tier's round cap.",
  },
]

const MARQUEE_TOP = ['Bluesky', 'Resend email', 'Google Trends', 'NewsAPI', 'Mastodon', 'Pollinations', 'OpenAI (BYOK)', 'Groq']
const MARQUEE_BOTTOM = ['LangGraph', 'Supabase', 'Postgres RLS', 'pgvector', 'LinUCB bandit', 'GitHub Actions', 'Edge Functions', 'LangSmith']

const STATS = [
  { value: 20, suffix: '', label: 'creative arms competing on real reward' },
  { value: 15, suffix: '', label: 'campaign languages, chosen per campaign' },
  { value: 2, suffix: '', label: 'human gates before anything goes live' },
  { value: 10, suffix: '', label: 'rounds per campaign on paid and BYOK tiers' },
]

const DIFFERENTIATORS = [
  {
    kicker: '01 · Signal',
    title: 'Real signal, not vibes',
    body: 'Feasibility is a weighted composite of live Trends, News and community search. Every input is shown next to the score, so nothing is a black-box number an LLM made up.',
  },
  {
    kicker: '02 · Learning',
    title: 'Learns which arm wins',
    body: 'A LinUCB contextual bandit chooses among 20 style × tone archetypes using real engagement. It shares what works within a domain without blindly copying across unrelated ones.',
  },
  {
    kicker: '03 · Control',
    title: 'You approve the risky parts',
    body: 'Two human gates sit inside the state machine itself: one before creative starts, one before anything is sent. Edit or reject at either.',
  },
]

// One photo per differentiator, in the same order: signal, learning, control.
const DIFFERENTIATOR_ART = [PHOTOS.signal, PHOTOS.strategy, PHOTOS.review]

const PROOF = [
  { kicker: 'Bluesky', text: 'Real posts to a real account. No mock client.', wide: true },
  { kicker: 'Email', text: 'Real sends via Resend, click-through tracked through our own redirect.' },
  { kicker: 'Security', text: "Row-level security, verified by trying to read another tenant's row." },
  { kicker: 'Memory', text: 'Cross-lingual retrieval: an English query matched a Spanish memory at 0.9 cosine.' },
  { kicker: 'Autonomy', text: 'Checkpointed in Postgres, so it survives across GitHub Actions runs that share nothing else.', wide: true },
  { kicker: 'Evals', text: 'An LLM-as-judge harness over an 18-idea golden set runs in CI on every push.' },
]

const TIERS = [
  {
    tier: 'Free',
    name: 'Runs on us',
    desc: 'Our own free-tier keys. The full loop at no cost to you.',
    feats: ['3 rounds per campaign', 'Every capability', 'Real distribution & metrics'],
    cta: 'Start free',
  },
  {
    tier: 'Subscribed',
    name: 'We front the cost',
    desc: 'Our paid-tier models, on your behalf.',
    feats: ['10 rounds per campaign', 'Sharper models throughout', 'Same real distribution & metrics'],
    cta: 'Subscribe',
    featured: true,
  },
  {
    tier: 'Bring your own key',
    name: 'Your key, our loop',
    desc: 'Encrypted server-side, never stored in plain text.',
    feats: ['10 rounds per campaign', 'Spend stays on your own account', 'No subscription needed'],
    cta: 'Connect a key',
  },
]

const FAQS = [
  {
    q: 'Does it really post and send?',
    a: 'Yes. Campaigns post to Bluesky and send email through Resend. The operator can switch on a dry-run mode that logs what would have been sent instead.',
  },
  {
    q: 'What does the free tier include?',
    a: 'The entire loop (feasibility, personas, creative, both gates, distribution and metrics) for up to 3 rounds per campaign, running on the platform’s free-tier models.',
  },
  {
    q: 'How is my own API key stored?',
    a: 'It is encrypted with AES-256-GCM inside a server-side function before it touches the database. The app only ever shows its last four characters.',
  },
  {
    q: 'Does the bandit share my campaigns with other users?',
    a: 'No. It shares only abstract archetype statistics keyed by domain, never your content. Your memory of past campaigns is private to you, enforced by Postgres row-level security.',
  },
  {
    q: 'Is billing real?',
    a: 'Not yet. Subscriptions are a stub toggled by the operator, so the three-tier model can be demonstrated without real payments.',
  },
  {
    q: 'Why isn’t Reddit a channel?',
    a: 'Reddit is on hold until API access is available. The code is in place behind a feature flag.',
  },
]

const HERO_LINES = [['One', 'idea', 'in.'], ['A', 'campaign', 'that'], ['keeps', 'getting', 'better.']]

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
                    const accent = word === 'better.'
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
              MarketingOS turns one line of text into a live ad campaign: scored against real market signals, written in
              your audience’s language, launched to real channels, and rewritten every round from what actually worked.
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
                  alt="Simulation of a MarketingOS campaign: an idea is scored for feasibility, personas are generated, the creative is approved at Gate 2, published to Bluesky and email, and reward climbs across rounds"
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
              <h2 className={styles.sectionTitle}>Nine steps. One state machine.</h2>
              <p className={styles.sectionSub}>
                Every campaign is a real LangGraph state machine, checkpointed in Postgres so it survives across
                short-lived runs.
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

        {/* Stacking differentiators */}
        <section className={styles.stackSection} id="why">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>Why it isn’t a wrapper</span>
              <h2 className={styles.sectionTitle}>Three things most “AI marketing” tools skip.</h2>
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
              <h2 className={styles.sectionTitle}>Everything here has actually posted, sent or run.</h2>
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
              <h2 className={styles.sectionTitle}>Three ways to pay for intelligence.</h2>
              <p className={styles.sectionSub}>
                The loop is identical on every tier. They differ only in total rounds and whose API key does the work.
              </p>
            </div>
            <div className={styles.pricingGrid}>
              {TIERS.map((t, i) => (
                <div
                  key={t.tier}
                  data-spot
                  data-reveal
                  className={`${styles.priceCard} ${t.featured ? styles.priceFeatured : ''} ${styles.reveal}`}
                  style={{ '--i': i } as CSSProperties}
                >
                  {t.featured && <span className={styles.priceFlag}>Most rounds per dollar</span>}
                  <span className={styles.priceTier}>{t.tier}</span>
                  <div className={styles.priceName}>{t.name}</div>
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
                  <Link className={`${styles.btn} ${t.featured ? styles.btnPrimary : styles.btnGhost} ${styles.btnBlock}`} to={signupTo}>
                    {t.cta}
                    <ArrowIcon />
                  </Link>
                </div>
              ))}
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
              <h2>Ready to stop babysitting a campaign?</h2>
              <p>Type one idea. Approve two gates. Watch it learn.</p>
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
