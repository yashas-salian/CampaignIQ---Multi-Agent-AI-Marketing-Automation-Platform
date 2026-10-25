import type { ReactNode } from 'react'
import { useSectionSpy } from '../lib/sectionSpy'
import PublicLayout from './PublicLayout'
import styles from './public.module.css'

export interface LegalSection {
  id: string
  title: string
  body: ReactNode
}

/** Long-form policy page: hero, a sticky table of contents, and readable prose. */
export default function LegalPage({
  eyebrow,
  title,
  updated,
  intro,
  sections,
}: {
  eyebrow: string
  title: string
  updated: string
  intro: ReactNode
  sections: LegalSection[]
}) {
  const [current, pick] = useSectionSpy(sections.map((s) => s.id))
  return (
    <PublicLayout>
      <section className={styles.enter}>
        <span className={styles.eyebrow}>{eyebrow}</span>
        <h1 className={styles.pageTitle}>{title}</h1>
        <p className={styles.lead}>Last updated {updated}</p>
      </section>
      <div className={styles.legal}>
        <nav className={styles.toc} aria-label="On this page">
          {sections.map((s) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`link-wipe ${s.id === current ? styles.tocCurrent : ''}`}
              aria-current={s.id === current ? 'location' : undefined}
              onClick={() => pick(s.id)}
            >
              {s.title}
            </a>
          ))}
        </nav>
        <article className={styles.prose}>
          <div className={styles.notice}>{intro}</div>
          {sections.map((s) => (
            <section key={s.id}>
              <h2 id={s.id}>{s.title}</h2>
              {s.body}
            </section>
          ))}
        </article>
      </div>
    </PublicLayout>
  )
}
