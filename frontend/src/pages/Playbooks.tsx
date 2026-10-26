import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { usePageLoading } from '../lib/loading'
import { toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './Playbooks.module.css'

interface Group {
  name: string
  mean: number
  n: number
}
interface Playbook {
  domain_category: string
  content: { headline: string; do: string[]; avoid: string[]; audience: string[]; next_test: string }
  stats: { rounds: number; campaigns: number; overall_mean: number; tones: Group[]; styles: Group[] }
  generated_at: string
}

const human = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** What CampaignIQ has learned per industry, written up after each finished campaign. */
export default function Playbooks() {
  const { t, i18n } = useTranslation()
  const { active } = useOrg()
  const [books, setBooks] = useState<Playbook[]>([])
  const [loaded, setLoaded] = useState(false)
  usePageLoading(!loaded)

  const load = useCallback(async () => {
    if (!active) return
    const { data, error } = await supabase
      .from('playbooks')
      .select('domain_category,content,stats,generated_at')
      .eq('org_id', active.id)
      .order('generated_at', { ascending: false })
    setLoaded(true)
    if (toastLoadError(t, error, () => load())) return
    setBooks((data as Playbook[]) ?? [])
  }, [active, t])

  useEffect(() => {
    load()
  }, [load])

  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' })
  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('pb.eyebrow')}</span>
          <h1 className={styles.title}>{t('pb.title')}</h1>
          <p className={styles.subtitle}>{t('pb.subtitle')}</p>
        </div>
      </header>

      {loaded && books.length === 0 ? (
        <section className={`${styles.panel} ${local.empty} ${styles.enter}`}>
          <h2>{t('pb.emptyTitle')}</h2>
          <p>{t('pb.emptyBody')}</p>
          <Link to="/dashboard" className={`${styles.btn} ${styles.primary}`}>
            {t('pb.emptyCta')}
          </Link>
        </section>
      ) : (
        <div className={local.grid}>
          {books.map((b, i) => {
            const bestTone = b.stats.tones[0]
            const bestStyle = b.stats.styles[0]
            const max = Math.max(0.01, ...b.stats.tones.map((g) => g.mean))
            return (
              <article key={b.domain_category} className={`${styles.panel} ${local.book} ${styles.enter}`} style={{ '--i': i } as CSSProperties}>
                <header className={local.bookHead}>
                  <span className={local.industry}>{human(b.domain_category)}</span>
                  <time dateTime={b.generated_at}>{t('pb.updated', { date: date.format(new Date(b.generated_at)) })}</time>
                </header>
                <h2 className={local.headline}>{b.content.headline}</h2>

                <dl className={local.stats}>
                  <div>
                    <dt>{t('pb.rounds')}</dt>
                    <dd>{b.stats.rounds}</dd>
                  </div>
                  <div>
                    <dt>{t('pb.campaigns')}</dt>
                    <dd>{b.stats.campaigns}</dd>
                  </div>
                  <div>
                    <dt>{t('pb.average')}</dt>
                    <dd>{b.stats.overall_mean.toFixed(2)}</dd>
                  </div>
                </dl>

                <div className={local.columns}>
                  <section>
                    <h3 className={local.do}>{t('pb.do')}</h3>
                    <ul>{b.content.do.map((d) => <li key={d}>{d}</li>)}</ul>
                  </section>
                  <section>
                    <h3 className={local.avoid}>{t('pb.avoid')}</h3>
                    <ul>{b.content.avoid.map((d) => <li key={d}>{d}</li>)}</ul>
                  </section>
                </div>

                {b.content.audience.length > 0 && (
                  <section className={local.audience}>
                    <h3>{t('pb.audience')}</h3>
                    <ul>{b.content.audience.map((d) => <li key={d}>{d}</li>)}</ul>
                  </section>
                )}

                <section className={local.evidence}>
                  <h3>{t('pb.evidence')}</h3>
                  <ul className={local.bars}>
                    {b.stats.tones.slice(0, 4).map((g) => (
                      <li key={g.name}>
                        <span>{human(g.name)}</span>
                        <span className={local.track}>
                          <span style={{ '--w': `${(g.mean / max) * 100}%` } as CSSProperties} />
                        </span>
                        <b>{g.mean.toFixed(2)}</b>
                        <small>n={g.n}</small>
                      </li>
                    ))}
                  </ul>
                  {bestTone && bestStyle && (
                    <p className={styles.muted}>{t('pb.best', { tone: human(bestTone.name).toLowerCase(), style: human(bestStyle.name).toLowerCase() })}</p>
                  )}
                </section>

                {b.content.next_test && (
                  <p className={local.next}>
                    <strong>{t('pb.next')}</strong> {b.content.next_test}
                  </p>
                )}
              </article>
            )
          })}
        </div>
      )}
      <p className={`${styles.muted} ${local.note}`}>{t('pb.note')}</p>
    </div>
  )
}
