import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import PublicLayout from '../components/PublicLayout'
import { ArrowIcon } from '../components/PublicNav'
import { REPO_URL, useAuthTargets } from '../lib/site'
import styles from '../components/public.module.css'
import local from './About.module.css'

const PILLARS = [
  {
    kicker: 'Decide',
    title: 'Know before you spend',
    body: 'A feasibility score from live search, news and social signals, then a recommendation (launch, test small, wait or kill) with every piece of evidence shown.',
  },
  {
    kicker: 'Create',
    title: 'Ads you can defend',
    body: 'Personas grounded in that research, ads built around your real product, a crash test before launch, and two human gates before anything goes out.',
  },
  {
    kicker: 'Prove',
    title: 'Learn what really worked',
    body: 'Real clicks and conversions teach the next round, and a randomized holdout measures the lift the campaign actually caused.',
  },
]

const PRINCIPLES = [
  { title: 'Real data or nothing', body: 'No mocked clients and no invented metrics. When a signal is unavailable the system says so; when the evidence is thin it answers "not enough evidence" instead of guessing.' },
  { title: 'People approve the risky parts', body: 'Two human gates sit inside the state machine. A campaign that turns unsafe after launch pauses itself, and only a person resumes it.' },
  { title: 'Consent first', body: 'Email goes only to people who opted in to hear from the brand, from the brand’s own account, with unsubscribe in every message. Nobody is scraped or bought.' },
  { title: 'Your data stays yours', body: 'Row-level security isolates every organisation, keys live in Supabase Vault, and the AI never sees a contact’s address or name.' },
]

const LAYERS = [
  { title: 'Agents', body: 'A LangGraph state machine runs intake, feasibility, personas, the decision engine, creative, crash test and feedback, each a plain capability that the API and MCP server reuse.' },
  { title: 'Learning', body: 'A LinUCB contextual bandit over 20 creative arms, multilingual pgvector memory, brand memory, and a fine-tuned Qwen2.5 classifier retrained weekly on human corrections.' },
  { title: 'Workers', body: 'GitHub Actions runs every campaign and an hourly sweep, resuming from Postgres checkpoints, so nothing depends on a server staying up.' },
  { title: 'Data', body: 'Supabase Postgres with row-level security on every table, Vault for secrets, an append-only audit log with a hash chain, and Edge Functions for the browser and the public API.' },
  { title: 'Safety', body: 'Brand-safety guardrails, prompt-injection fencing, a crash test, a circuit breaker that blocks sends in the database, and per-recipient email suppression.' },
  { title: 'Evidence', body: 'A golden-set eval with an LLM judge, and fixed benchmarks for the decision engine, proof of impact, creative fatigue and brand memory, all run in CI.' },
]

const STACK = ['Python 3.12', 'LangGraph', 'Pydantic', 'Groq', 'Gemini', 'FLUX', 'Qwen2.5 + LoRA', 'Supabase', 'Postgres RLS', 'pgvector', 'Vault',
  'Edge Functions', 'GitHub Actions', 'Resend', 'Stripe', 'React 19', 'Vite', 'TypeScript', 'Playwright']

export default function About() {
  const { signupTo } = useAuthTargets()
  return (
    <PublicLayout>
      <section className={styles.enter}>
        <span className={styles.eyebrow}>About CampaignIQ</span>
        <h1 className={styles.pageTitle}>
          A marketing loop that <em>proves</em> what it did.
        </h1>
        <p className={styles.lead}>
          Most AI marketing tools write copy and stop there. CampaignIQ takes one product through the whole campaign:
          whether to run it at all, who it's for, an ad built around the real product, a launch to social and to your own
          subscribers, and a measurement of what it actually caused. Then it uses what happened to do better next round.
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
          The work CampaignIQ automates: planning, testing and rewriting campaigns. Photo by{' '}
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
        <h2 className={styles.sectionTitle}>Decide, create, prove. One closed loop.</h2>
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
        <span className={styles.eyebrow}>How it's built</span>
        <h2 className={styles.sectionTitle}>Six layers, each doing one job.</h2>
        <p className={styles.sectionLead}>Built to run on free tiers without cutting corners on safety or evidence.</p>
        <ol className={local.timeline}>
          {LAYERS.map((m, i) => (
            <li key={m.title}>
              <span className={local.tag}>{String(i + 1).padStart(2, '0')}</span>
              <div>
                <h3>{m.title}</h3>
                <p>{m.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className={`${styles.section} ${local.builder}`}>
        <div>
          <span className={styles.eyebrow}>The builder</span>
          <h2 className={styles.sectionTitle}>Built end to end by Yashas Salian.</h2>
          <p className={styles.sectionLead}>
            CampaignIQ is a portfolio project exploring what an agentic system looks like when it has to meet real APIs,
            real customers' inboxes and real engagement, not a demo script. The full source, design notes and benchmarks are
            public.
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
