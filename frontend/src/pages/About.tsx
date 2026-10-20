import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import PublicLayout from '../components/PublicLayout'
import { ArrowIcon } from '../components/PublicNav'
import { REPO_URL, useAuthTargets } from '../lib/site'
import styles from '../components/public.module.css'
import local from './About.module.css'

const PILLARS = [
  {
    kicker: 'Score',
    title: 'Know before you spend',
    body: 'Every idea gets a 0–100 feasibility score built from live Google Trends, news volume and community search, with each signal shown next to the number.',
  },
  {
    kicker: 'Create',
    title: 'Creative with a reason',
    body: 'Personas grounded in that research, copy and imagery generated in your audience’s language, and a simulated panel that reacts before anything real goes out.',
  },
  {
    kicker: 'Learn',
    title: 'Better every round',
    body: 'Real engagement from real posts and emails becomes the reward for a contextual bandit, so the next round leans toward what actually worked.',
  },
]

const PRINCIPLES = [
  { title: 'Real data or nothing', body: 'No mocked clients and no invented metrics. If a signal is unavailable, the system says so and degrades to neutral instead of guessing.' },
  { title: 'People approve the risky parts', body: 'Two human gates sit inside the state machine itself. Nothing is written before the first, and nothing is sent before the second.' },
  { title: 'Your data stays yours', body: 'Postgres row-level security isolates every tenant. Your own API keys are encrypted server-side and only ever shown as their last four characters.' },
  { title: 'Free by default', body: 'The whole loop runs on free-tier infrastructure. Paid models are an upgrade, never a requirement.' },
]

const MILESTONES = [
  { tag: 'M1', title: 'Provider layer & capabilities', body: 'Free/paid provider registry, real integrations for Trends, news, Bluesky, Mastodon, Resend and image generation.' },
  { tag: 'M2', title: 'Evaluation harness', body: 'An 18-idea golden set with an LLM judge, running in CI so quality regressions fail the build.' },
  { tag: 'M3', title: 'Human gates & pre-flight', body: 'Checkpointed approval gates and a synthetic persona panel between creative and launch.' },
  { tag: 'M4', title: 'Multi-tenancy & BYOK', body: 'Supabase Auth, row-level security on every table, and encrypted bring-your-own-key support.' },
  { tag: 'M5', title: 'The autonomous loop', body: 'Metrics collection, feedback, tier round caps and GitHub Actions workers that resume from Postgres checkpoints.' },
  { tag: 'M6', title: 'Learning & memory', body: 'A LinUCB contextual bandit over 20 creative arms, per-user pgvector memory, and a metrics view.' },
]

const STACK = ['Python 3.12', 'LangGraph', 'Pydantic', 'Groq', 'OpenAI (BYOK)', 'Supabase', 'Postgres RLS', 'pgvector', 'Edge Functions', 'GitHub Actions', 'React 19', 'Vite', 'TypeScript', 'LangSmith']

export default function About() {
  const { signupTo } = useAuthTargets()
  return (
    <PublicLayout>
      <section className={styles.enter}>
        <span className={styles.eyebrow}>About MarketingOS</span>
        <h1 className={styles.pageTitle}>
          A marketing loop that <em>learns</em> from what really happens.
        </h1>
        <p className={styles.lead}>
          Most AI marketing tools write copy and stop there. MarketingOS takes one line of text through the whole
          campaign (research, audience, creative, launch and measurement), then uses real engagement to decide what to
          try next.
        </p>
      </section>

      {/* Free under the Unsplash License (unsplash.com/license); credited below. */}
      <figure className={`${local.heroMedia} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
        <img
          src="https://images.unsplash.com/photo-1676276376052-dc9c9c0b6917?auto=format&fit=crop&w=1600&q=70"
          srcSet="https://images.unsplash.com/photo-1676276376052-dc9c9c0b6917?auto=format&fit=crop&w=800&q=70 800w, https://images.unsplash.com/photo-1676276376052-dc9c9c0b6917?auto=format&fit=crop&w=1600&q=70 1600w, https://images.unsplash.com/photo-1676276376052-dc9c9c0b6917?auto=format&fit=crop&w=2400&q=70 2400w"
          sizes="(max-width: 1200px) 100vw, 1136px"
          alt="A marketing team planning a week of social media content on a whiteboard covered in sticky notes"
          loading="lazy"
          decoding="async"
        />
        <figcaption>
          The work MarketingOS automates: planning, testing and rewriting campaigns. Photo by{' '}
          <a href="https://unsplash.com/@walls_io" target="_blank" rel="noopener noreferrer">
            Walls.io
          </a>{' '}
          on{' '}
          <a
            href="https://unsplash.com/photos/two-women-standing-in-front-of-a-whiteboard-with-sticky-notes-on-it-wODKtuRipCA"
            target="_blank"
            rel="noopener noreferrer"
          >
            Unsplash
          </a>
        </figcaption>
      </figure>

      <section className={styles.section}>
        <span className={styles.eyebrow}>What it does</span>
        <h2 className={styles.sectionTitle}>Three jobs, one closed loop.</h2>
        <div className={`${styles.grid3} ${local.gapTop}`}>
          {PILLARS.map((p) => (
            <article className={styles.card} key={p.title}>
              <span className={styles.cardKicker}>{p.kicker}</span>
              <h3>{p.title}</h3>
              <p>{p.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <span className={styles.eyebrow}>Principles</span>
        <h2 className={styles.sectionTitle}>The rules it’s built on.</h2>
        <div className={`${styles.grid2} ${local.gapTop}`}>
          {PRINCIPLES.map((p, i) => (
            <article className={`${styles.card} ${local.principle}`} key={p.title}>
              <span className={local.num}>{String(i + 1).padStart(2, '0')}</span>
              <div>
                <h3>{p.title}</h3>
                <p>{p.body}</p>
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <span className={styles.eyebrow}>How it was built</span>
        <h2 className={styles.sectionTitle}>Six milestones, shipped in order.</h2>
        <p className={styles.sectionLead}>Each milestone was verified live against real services before the next one started.</p>
        <ol className={local.timeline}>
          {MILESTONES.map((m) => (
            <li key={m.tag}>
              <span className={local.tag}>{m.tag}</span>
              <div>
                <h3>{m.title}</h3>
                <p>{m.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={`${styles.section} ${local.builder}`}>
        <div className={`${styles.placeholder} ${local.portrait}`}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.5" />
            <path d="M4 21c1.5-4 4.5-6 8-6s6.5 2 8 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
          <span className={styles.placeholderLabel}>Portrait (placeholder)</span>
        </div>
        <div>
          <span className={styles.eyebrow}>The builder</span>
          <h2 className={styles.sectionTitle}>Built end to end by Yashas Salian.</h2>
          <p className={styles.sectionLead}>
            MarketingOS is a portfolio project exploring what an agentic system looks like when it has to meet real
            APIs, real users and real engagement, not a demo script. The full source and design notes are public.
          </p>
          <div className={local.stack}>
            {STACK.map((s) => (
              <span key={s}>{s}</span>
            ))}
          </div>
          <div className={styles.ctaRow}>
            <Link className={`${styles.btn} ${styles.btnPrimary}`} to={signupTo}>
              Start a campaign
              <ArrowIcon className={styles.arrow} />
            </Link>
            <a className={`${styles.btn} ${styles.btnGhost}`} href={REPO_URL} target="_blank" rel="noopener noreferrer">
              View the source
            </a>
          </div>
        </div>
      </section>
    </PublicLayout>
  )
}
