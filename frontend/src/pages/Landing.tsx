import { useEffect, useRef } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTheme } from '../lib/ThemeContext'
import { useSession } from '../lib/useAuth'
import styles from './Landing.module.css'

const LOOP_STEPS = [
  {
    title: 'Idea intake',
    desc: "Classifies the idea into a domain — fitness, B2B SaaS, food & beverage — the same tag the bandit later uses as context.",
  },
  {
    title: 'Feasibility',
    desc: "Google Trends, NewsAPI, and Bluesky/Mastodon search — queried in the campaign's own target language — combine into a transparent 0–100 score with a written rationale.",
  },
  {
    title: 'Audience',
    desc: 'Generates ideal-customer personas grounded in that research, one of which drives the whole round.',
  },
  {
    title: 'Human gate — idea',
    desc: 'You approve, edit, or reject before a single word of creative gets written.',
  },
  {
    title: 'Creative',
    desc: "A contextual bandit picks the style and tone archetype from real past engagement, then the copy and image are generated to match — in-language, novelty-checked against your own past creative.",
  },
  {
    title: 'Pre-flight',
    desc: "A simulated persona panel reacts before anything real goes out. Fails twice, and it tries again with the best attempt.",
  },
  {
    title: 'Human gate — creative',
    desc: 'A second, final approval before real spend or real sends.',
  },
  {
    title: 'Distribute',
    desc: "Real posts to Bluesky, real email via Resend — with click-through tracked through your own redirect, not a third party's word for it.",
  },
  {
    title: 'Measure & feed back',
    desc: "Engagement becomes the bandit's reward signal. The next round's creative is rewritten from what actually happened — up to your tier's round cap.",
    feedback: true,
  },
]

const STAT_CARDS = [
  { kicker: 'Bluesky', text: 'Real posts to a real Bluesky account — no mock client, ever.', accent: 'moss' },
  { kicker: 'Email', text: 'Real sends via Resend, with click-through tracked through our own redirect.', accent: 'brass' },
  { kicker: 'Bandit', text: '20 creative arms, one LinUCB contextual bandit, learning from real reward.', accent: 'berry' },
  { kicker: 'Language', text: '15 languages supported — chosen per campaign, independent of the input language.', accent: 'moss' },
  { kicker: 'Security', text: "Postgres row-level security — verified live by trying to read another tenant's row.", accent: 'brass' },
  { kicker: 'Memory', text: 'Cross-lingual retrieval confirmed at 0.9 cosine similarity — English query, Spanish result.', accent: 'berry' },
  { kicker: 'Autonomy', text: 'Checkpointed in Postgres — survives across GitHub Actions runs that share nothing else.', accent: 'moss' },
] as const

const SCRUB_NOTES = [
  { text: 'Feasibility scored before a dollar moves.', cls: 'scrubNote1', lo: 0.08, hi: 0.5, speed: 0.6 },
  { text: 'Every arm competes on real reward.', cls: 'scrubNote2', lo: 0.3, hi: 0.72, speed: 1 },
  { text: 'You approve the risky parts.', cls: 'scrubNote3', lo: 0.55, hi: 1, speed: 1.4 },
] as const

const CheckIcon = () => (
  <svg viewBox="0 0 24 24" fill="none"><path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" /></svg>
)

export default function Landing() {
  const { session, loading } = useSession()
  const navigate = useNavigate()
  const containerRef = useRef<HTMLDivElement>(null)
  const heroLine1Ref = useRef<HTMLSpanElement>(null)
  const heroLine2Ref = useRef<HTMLSpanElement>(null)
  const scrubSectionRef = useRef<HTMLDivElement>(null)
  const scrubTextRef = useRef<HTMLHeadingElement>(null)
  const { theme, toggleTheme } = useTheme()

  // Logged-in visitors land on the app, not the marketing page.
  useEffect(() => {
    if (!loading && session) navigate('/dashboard', { replace: true })
  }, [loading, session, navigate])

  // Hero heading shear: the two lines drift apart in opposite horizontal
  // directions as the page scrolls -- one left, one right -- mirroring the
  // hero heading's own scroll behavior.
  useEffect(() => {
    const line1 = heroLine1Ref.current
    const line2 = heroLine2Ref.current
    if (!line1 || !line2) return
    const MAX_DRIFT = 90
    const FACTOR = 0.18

    function update() {
      const drift = Math.min(MAX_DRIFT, window.scrollY * FACTOR)
      line1!.style.transform = `translateX(${-drift}px)`
      line2!.style.transform = `translateX(${drift}px)`
    }

    update()
    let ticking = false
    function onScroll() {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          update()
          ticking = false
        })
        ticking = true
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Scroll-triggered section reveals.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const els = Array.from(container.querySelectorAll<HTMLElement>('[data-reveal]'))
    if (!('IntersectionObserver' in window)) {
      els.forEach((el) => el.classList.add(styles.revealIn))
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add(styles.revealIn)
            io.unobserve(entry.target)
          }
        })
      },
      { threshold: 0.15, rootMargin: '0px 0px -60px 0px' },
    )
    els.forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [])

  // Scroll-scrubbed loop diagram: each real graph node lights up as it
  // crosses the activation line, mirroring how the state machine actually
  // executes one node at a time.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const nodes = Array.from(container.querySelectorAll<HTMLElement>('[data-loop-node]'))
    if (!nodes.length) return

    function update() {
      const trigger = window.innerHeight * 0.62
      nodes.forEach((node) => {
        const rect = node.getBoundingClientRect()
        if (rect.top < trigger) node.classList.add(styles.loopActive)
        else node.classList.remove(styles.loopActive)
      })
    }

    update()
    let ticking = false
    function onScroll() {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          update()
          ticking = false
        })
        ticking = true
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Pinned horizontal scrub: a tall spacer holds a sticky viewport-height
  // stage in place while a giant headline slides right-to-left in step with
  // scroll progress through that spacer, and annotation notes fade in/out at
  // fixed progress windows along the way.
  useEffect(() => {
    const section = scrubSectionRef.current
    const text = scrubTextRef.current
    if (!section || !text) return
    const notes = Array.from(section.querySelectorAll<HTMLElement>('[data-scrub-note]'))

    function update() {
      const rect = section!.getBoundingClientRect()
      const scrollable = rect.height - window.innerHeight
      const progress = scrollable > 0 ? Math.min(1, Math.max(0, -rect.top / scrollable)) : 0
      const startX = window.innerWidth
      const endX = -text!.scrollWidth
      text!.style.transform = `translateX(${startX + (endX - startX) * progress}px)`
      notes.forEach((note) => {
        const lo = parseFloat(note.dataset.lo ?? '0')
        const hi = parseFloat(note.dataset.hi ?? '1')
        const speed = parseFloat(note.dataset.speed ?? '1')
        // Each note drifts at its own fraction of the headline's speed, so
        // the stack reads as layered depth rather than a flat overlay.
        note.style.setProperty('--driftX', `${-progress * 260 * speed}px`)
        note.style.setProperty('--driftY', `${-progress * 40 * speed}px`)
        note.classList.toggle(styles.scrubNoteIn, progress >= lo && progress <= hi)
      })
    }

    update()
    let ticking = false
    function onScroll() {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          update()
          ticking = false
        })
        ticking = true
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', update)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', update)
    }
  }, [])

  return (
    <div className={styles.page} ref={containerRef}>
      <header className={styles.nav}>
        <div className={`${styles.wrap} ${styles.navInner}`}>
          <div className={styles.logo}>
            <svg viewBox="0 0 24 24" fill="none">
              <path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M12 3v5l4-2.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            MarketingOS
          </div>
          <nav className={styles.links}>
            <a href="#loop">The Loop</a>
            <a href="#proof">Proof</a>
            <a href="#platform">Platform</a>
            <a href="#pricing">Pricing</a>
          </nav>
          <div className={styles.navRight}>
            <button className={styles.themeToggle} aria-label="Toggle color theme" onClick={toggleTheme}>
              {theme === 'light' ? (
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z" stroke="currentColor" strokeWidth="1.8" />
                  <path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3a9 9 0 1 0 9 9c0-.46-.04-.92-.1-1.36A5.4 5.4 0 0 1 12 3z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
                </svg>
              )}
            </button>
            <Link className={`${styles.btn} ${styles.btnGhost}`} to="/login">
              Log in
            </Link>
            <Link className={`${styles.btn} ${styles.btnPrimary}`} to="/login">
              Get started
            </Link>
          </div>
        </div>
      </header>

      <main>
        <section className={styles.hero} id="hero">
          <div className={`${styles.wrap} ${styles.heroGrid}`}>
            <div className={styles.heroCopy}>
              <span className={`${styles.eyebrow} ${styles.reveal} ${styles.revealIn}`}>
                <span className={styles.dot} />
                Currently running round 3 of 3
              </span>
              <h1 className={`${styles.reveal} ${styles.revealIn} ${styles.reveal1}`}>
                <span className={styles.heroLine} ref={heroLine1Ref}>
                  One idea in.
                </span>
                <span className={styles.heroLine} ref={heroLine2Ref}>
                  A campaign that <em>never stops</em> improving.
                </span>
              </h1>
              <p className={`${styles.heroSub} ${styles.reveal} ${styles.revealIn} ${styles.reveal2}`}>
                MarketingOS turns a single line of text into a live ad campaign — scored against real market
                signals, produced in the language your audience actually speaks, launched to real channels, and
                rewritten every round based on what actually worked.
              </p>
              <div className={`${styles.heroCtas} ${styles.reveal} ${styles.revealIn} ${styles.reveal3}`}>
                <Link className={`${styles.btn} ${styles.btnPrimary}`} to="/login">
                  Start a campaign
                </Link>
                <a className={styles.linkCta} href="#loop">
                  See the loop
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                    <path d="M12 5v14M5 12l7 7 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </a>
              </div>
            </div>
            <div className={`${styles.mockStage} ${styles.reveal} ${styles.revealIn} ${styles.reveal4}`}>
              <div className={`${styles.mockCard} ${styles.primary}`}>
                <div className={styles.mockLabel}>Round 3 · food_beverage</div>
                <div className={styles.mockTitle}>Feasibility score</div>
                <div className={styles.mockRow}>
                  <span className={styles.mockScore}>78</span>
                  <span>/ 100</span>
                </div>
                <div className={styles.mockBar}>
                  <span style={{ width: '78%', background: 'var(--moss)' }} />
                </div>
                <div className={styles.mockBadges}>
                  <span className={styles.mockBadge}>trend ↑</span>
                  <span className={styles.mockBadge}>es-ES</span>
                  <span className={styles.mockBadge}>bluesky</span>
                </div>
              </div>
              <div className={`${styles.mockCard} ${styles.secondary}`}>
                <div className={styles.mockLabel}>Arm selected</div>
                <div className={styles.mockTitleSm}>testimonial_social_proof</div>
                <div className={styles.mockRow}>
                  <span>copy tone</span>
                  <span className={styles.mockBadge}>humorous</span>
                </div>
                <div className={styles.mockSpark}>
                  <div style={{ height: '20%', background: 'var(--parchment-3)' }} />
                  <div style={{ height: '35%', background: 'var(--parchment-3)' }} />
                  <div style={{ height: '30%', background: 'var(--parchment-3)' }} />
                  <div style={{ height: '55%', background: 'var(--brass)' }} />
                  <div style={{ height: '80%', background: 'var(--brass)' }} />
                </div>
              </div>
              <div className={`${styles.mockCard} ${styles.tertiary}`}>
                <div className={styles.mockLabel}>Gate 2</div>
                <div className={styles.mockTitleXs}>Awaiting your approval</div>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.loopSection} id="loop">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>
                <span className={styles.dot} />
                How it actually runs
              </span>
              <h2>
                Nine steps. One state machine.
                <br />
                Zero manual babysitting.
              </h2>
              <p>
                Every campaign is a real LangGraph state machine, checkpointed in Postgres so it survives across
                ephemeral runs. Scroll through one full round.
              </p>
            </div>
            <div className={styles.loopTrack}>
              {LOOP_STEPS.map((step, i) => (
                <div className={styles.loopNode} data-loop-node key={step.title}>
                  <div className={styles.loopNum}>{i + 1}</div>
                  <div className={styles.loopBody}>
                    <div className={`${styles.loopTitle} ${step.feedback ? styles.loopFeedback : ''}`}>{step.title}</div>
                    <div className={styles.loopDesc}>{step.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <div className={styles.scrubSection} ref={scrubSectionRef}>
          <div className={styles.scrubSticky}>
            <h2 className={styles.scrubText} ref={scrubTextRef}>
              Round three already knows what round one didn&rsquo;t.
            </h2>
            {SCRUB_NOTES.map((note) => (
              <div
                key={note.text}
                className={`${styles.scrubNote} ${styles[note.cls]}`}
                data-scrub-note
                data-lo={note.lo}
                data-hi={note.hi}
                data-speed={note.speed}
              >
                {note.text}
              </div>
            ))}
          </div>
        </div>

        <section id="features">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>
                <span className={styles.dot} />
                Why it isn't a wrapper
              </span>
              <h2>Three things most "AI marketing" tools skip.</h2>
            </div>
            <div className={styles.triptych}>
              <div className={`${styles.featureCard} ${styles.reveal} ${styles.reveal1}`} data-reveal>
                <div className={styles.featureIcon} style={{ background: 'color-mix(in srgb, var(--moss) 20%, transparent)', color: 'var(--moss)' }}>
                  <svg viewBox="0 0 24 24" fill="none">
                    <path d="M3 17l6-6 4 4 8-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>
                <h3>Real signal, not vibes</h3>
                <p>
                  Feasibility is a transparent, weighted composite of live Trends, News, and community search —
                  never a black-box number an LLM made up.
                </p>
              </div>
              <div className={`${styles.featureCard} ${styles.reveal} ${styles.reveal2}`} data-reveal>
                <div className={styles.featureIcon} style={{ background: 'color-mix(in srgb, var(--brass) 20%, transparent)', color: 'var(--brass)' }}>
                  <svg viewBox="0 0 24 24" fill="none">
                    <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
                    <path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                </div>
                <h3>Learns which arm wins</h3>
                <p>
                  A LinUCB contextual bandit picks the creative archetype from real engagement — shared across
                  every campaign in a domain, without blindly copying across unrelated ones.
                </p>
              </div>
              <div className={`${styles.featureCard} ${styles.reveal} ${styles.reveal3}`} data-reveal>
                <div className={styles.featureIcon} style={{ background: 'color-mix(in srgb, var(--berry) 20%, transparent)', color: 'var(--berry)' }}>
                  <svg viewBox="0 0 24 24" fill="none">
                    <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2" />
                  </svg>
                </div>
                <h3>You approve the risky parts</h3>
                <p>
                  Two human gates — before creative starts, and before anything goes out — wired directly into
                  the state machine, not bolted on after.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.proofSection} id="proof">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>
                <span className={styles.dot} />
                Not simulated
              </span>
              <h2>Everything below has actually posted, actually sent, actually run.</h2>
            </div>
          </div>
          <div className={styles.marqueeViewport}>
            <div className={styles.marqueeTrack}>
              {[...STAT_CARDS, ...STAT_CARDS].map((s, i) => (
                <div
                  key={i}
                  className={styles.statCard}
                  style={{
                    background: `color-mix(in srgb, var(--${s.accent}) 16%, var(--mos-surface))`,
                    border: `1px solid color-mix(in srgb, var(--${s.accent}) 30%, transparent)`,
                  }}
                >
                  <span className={styles.statKicker} style={{ color: `var(--${s.accent})` }}>
                    {s.kicker}
                  </span>
                  {s.text}
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="platform">
          <div className={`${styles.wrap} ${styles.platformGrid}`}>
            <div className={`${styles.reveal} ${styles.reveal1}`} data-reveal>
              <span className={styles.eyebrow}>
                <span className={styles.dot} />
                Under the hood
              </span>
              <h2 style={{ marginTop: 16 }}>The part that makes it worth building.</h2>
              <p style={{ color: 'var(--mos-text-muted)', fontSize: 16, marginTop: 16, lineHeight: 1.6 }}>
                Every capability — feasibility, personas, creative, distribution, metrics — is a plain function
                first, wired into the graph second. The same function backs the autonomous loop and a one-off
                test run.
              </p>
              <ul className={styles.checklist}>
                <li>
                  <span className={styles.check}>
                    <CheckIcon />
                  </span>
                  Postgres row-level security, verified by trying to read another tenant's row and watching it fail
                </li>
                <li>
                  <span className={styles.check}>
                    <CheckIcon />
                  </span>
                  Per-user memory in pgvector — retrieval and novelty-checks never cross tenants
                </li>
                <li>
                  <span className={styles.check}>
                    <CheckIcon />
                  </span>
                  Checkpointed across ephemeral GitHub Actions runs — no server ever stays warm
                </li>
              </ul>
              <a className={`${styles.btn} ${styles.btnGhost}`} href="#pricing">
                See how it's priced
              </a>
            </div>
            <div className={`${styles.reveal} ${styles.reveal2}`} data-reveal>
              <div className={`${styles.mockCard} ${styles.mockStatic}`}>
                <div className={styles.mockLabel}>Reward trend</div>
                <div className={styles.mockTitle}>Across 3 rounds</div>
                <div className={styles.mockSpark} style={{ height: 70, marginTop: 20 }}>
                  <div style={{ height: '15%', background: 'var(--parchment-3)' }} />
                  <div style={{ height: '22%', background: 'var(--parchment-3)' }} />
                  <div style={{ height: '40%', background: 'var(--moss)' }} />
                  <div style={{ height: '58%', background: 'var(--moss)' }} />
                  <div style={{ height: '71%', background: 'var(--brass)' }} />
                  <div style={{ height: '88%', background: 'var(--brass)' }} />
                </div>
                <div className={styles.mockRow}>
                  <span>winning arm</span>
                  <span className={styles.mockBadge}>lifestyle_aspirational</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="pricing">
          <div className={styles.wrap}>
            <div className={`${styles.sectionHead} ${styles.reveal}`} data-reveal>
              <span className={styles.eyebrow}>
                <span className={styles.dot} />
                Services
              </span>
              <h2>Three ways to pay for intelligence.</h2>
              <p>
                The loop is identical either way — the tiers differ only in total optimization budget and whose
                API key is doing the work.
              </p>
            </div>
            <div className={styles.pricingGrid}>
              <div className={`${styles.priceCard} ${styles.reveal} ${styles.reveal1}`} data-reveal>
                <span className={styles.priceTier}>Free</span>
                <div className={styles.priceName}>Runs on us</div>
                <p className={styles.priceTierDesc}>Our own free-tier keys. The full loop, no cost to you.</p>
                <ul className={styles.priceFeats}>
                  <li>3 rounds per campaign</li>
                  <li>Every capability, unrestricted</li>
                  <li>Real distribution &amp; real metrics</li>
                </ul>
                <Link className={`${styles.btn} ${styles.btnGhost}`} to="/login">
                  Start free
                </Link>
              </div>
              <div className={`${styles.priceCard} ${styles.priceFeatured} ${styles.reveal} ${styles.reveal2}`} data-reveal>
                <span className={styles.priceTier}>Subscribed</span>
                <div className={styles.priceName}>We front the cost</div>
                <p className={styles.priceTierDesc}>Our paid-tier keys, on your behalf.</p>
                <ul className={styles.priceFeats}>
                  <li>10 rounds per campaign</li>
                  <li>Sharper models throughout</li>
                  <li>Same real distribution &amp; metrics</li>
                </ul>
                <Link className={`${styles.btn} ${styles.btnPrimary}`} to="/login">
                  Subscribe
                </Link>
              </div>
              <div className={`${styles.priceCard} ${styles.reveal} ${styles.reveal3}`} data-reveal>
                <span className={styles.priceTier}>Bring your own key</span>
                <div className={styles.priceName}>Your key, our loop</div>
                <p className={styles.priceTierDesc}>Encrypted server-side, never stored in plain text.</p>
                <ul className={styles.priceFeats}>
                  <li>10 rounds per campaign</li>
                  <li>Every dollar of spend stays yours to track</li>
                  <li>No subscription required</li>
                </ul>
                <Link className={`${styles.btn} ${styles.btnGhost}`} to="/login">
                  Connect a key
                </Link>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.ctaBand}>
          <div className={`${styles.wrap} ${styles.reveal}`} data-reveal>
            <h2>Ready to stop babysitting a campaign?</h2>
            <Link className={`${styles.btn} ${styles.btnPrimary} ${styles.ctaBandBtn}`} to="/login">
              Start a campaign
            </Link>
          </div>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={styles.wrap}>
          <div className={styles.footerTop}>
            <div className={styles.footerBrand}>
              <div className={styles.logo}>
                <svg viewBox="0 0 24 24" fill="none">
                  <path d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  <path d="M12 3v5l4-2.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                MarketingOS
              </div>
              <p>
                An agentic ad-campaign platform: idea → feasibility → creative → distribution → feedback, on a
                closed loop, entirely on free-tier infrastructure by default.
              </p>
            </div>
            <div className={styles.footerCol}>
              <h4>Product</h4>
              <a href="#loop">The Loop</a>
              <a href="#platform">Platform</a>
              <a href="#pricing">Pricing</a>
            </div>
            <div className={styles.footerCol}>
              <h4>Proof</h4>
              <a href="#proof">What's real</a>
              <a href="#features">Differentiators</a>
            </div>
            <div className={styles.footerCol}>
              <h4>Company</h4>
              <a
                href="https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform"
                target="_blank"
                rel="noopener noreferrer"
              >
                Source on GitHub
              </a>
              <a href="mailto:safiya.khan@nonstopio.com">Get in touch</a>
            </div>
            <div className={styles.footerCol}>
              <h4>Legal</h4>
              <a href="#pricing">Billing is stubbed</a>
              <a href="#platform">No fake data, anywhere</a>
            </div>
          </div>
          <div className={styles.footerBottom}>
            <span>© 2026 MarketingOS — a portfolio project, built end-to-end with real APIs.</span>
            <span>Built with LangGraph · Supabase · React</span>
          </div>
        </div>
      </footer>
    </div>
  )
}
