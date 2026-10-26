import { useCallback, useEffect, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'

import { usePageLoading } from '../lib/loading'
import { toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './ModelCard.module.css'

interface Metrics {
  golden?: number
  golden_n?: number
  heldout?: number
  heldout_n?: number
  corrections?: number
  median_ms?: number
  invalid_outputs?: number
  top_confusions?: [string, string, number][]
  label?: string
}
interface Version {
  version: string
  revision: string | null
  trained_at: string
  base_model: string
  method: string | null
  data: Record<string, number | string>
  metrics: Metrics
  baseline_metrics: Metrics | null
  notes: string | null
}
interface Card {
  versions: Version[]
  deployment: { active_revision: string | null; candidate_revision: string | null; mode: 'off' | 'shadow' | 'canary'; canary_percent: number; updated_at: string } | null
  shadow: { compared: number; agreement: number | null } | null
  corrections: { total: number; since_last_training: number; last_30_days: number }
}

const pct = (v?: number) => (typeof v === 'number' ? `${Math.round(v * 100)}%` : '—')
const human = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Two bars, ours vs the starting point, for one metric. */
function Compare({ label, ours, base, baseLabel, note }: { label: string; ours?: number; base?: number; baseLabel: string; note: string }) {
  const lift = typeof ours === 'number' && typeof base === 'number' ? Math.round((ours - base) * 100) : null
  return (
    <div className={local.compare}>
      <div className={local.compareHead}>
        <strong>{label}</strong>
        {lift !== null && <span className={local.lift}>{lift >= 0 ? `+${lift}` : lift} pts</span>}
      </div>
      <div className={local.barRow}>
        <span>CampaignIQ</span>
        <span className={local.track}>
          <span className={local.fillOurs} style={{ '--w': `${(ours ?? 0) * 100}%` } as CSSProperties} />
        </span>
        <b>{pct(ours)}</b>
      </div>
      <div className={local.barRow}>
        <span>{baseLabel}</span>
        <span className={local.track}>
          <span className={local.fillBase} style={{ '--w': `${(base ?? 0) * 100}%` } as CSSProperties} />
        </span>
        <b>{pct(base)}</b>
      </div>
      <p className={styles.muted}>{note}</p>
    </div>
  )
}

/** Our own model, in one screen: what it is, how good it is, how it keeps learning. */
export default function ModelCard() {
  const { t, i18n } = useTranslation()
  const [card, setCard] = useState<Card | null>(null)
  const [loaded, setLoaded] = useState(false)
  usePageLoading(!loaded)

  const load = useCallback(async () => {
    const { data, error } = await supabase.rpc('model_card')
    setLoaded(true)
    if (toastLoadError(t, error, () => load())) return
    setCard(data as Card)
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  const date = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' })
  const current = card?.versions[0]
  const dep = card?.deployment
  const m = current?.metrics ?? {}
  const base = current?.baseline_metrics ?? {}

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('mc.eyebrow')}</span>
          <h1 className={styles.title}>{t('mc.title')}</h1>
          <p className={styles.subtitle}>{t('mc.subtitle')}</p>
        </div>
        {current && (
          <span className={local.versionBadge}>
            {current.version} · {date.format(new Date(current.trained_at))}
          </span>
        )}
      </header>

      {current && (
        <>
          <section className={local.facts}>
            {[
              [t('mc.factTask'), t('mc.factTaskValue', { count: Number(current.data.labels ?? 12) })],
              [t('mc.factBase'), current.base_model],
              [t('mc.factMethod'), current.method ?? '—'],
              [t('mc.factData'), t('mc.factDataValue', { synthetic: current.data.synthetic_examples ?? '—', corrections: current.data.corrections_used ?? 0 })],
            ].map(([k, v], i) => (
              <div key={k} className={`${styles.panel} ${local.fact} ${styles.enter}`} style={{ '--i': i + 1 } as CSSProperties}>
                <span>{k}</span>
                <strong>{v}</strong>
              </div>
            ))}
          </section>

          <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('mc.quality')}</h2>
                <p className={styles.panelSub}>{t('mc.qualitySub')}</p>
              </div>
            </div>
            <div className={local.compares}>
              <Compare label={t('mc.golden', { n: m.golden_n ?? '' })} ours={m.golden} base={base.golden} baseLabel={base.label ?? t('mc.base')} note={t('mc.goldenNote')} />
              <Compare label={t('mc.heldout', { n: m.heldout_n ?? '' })} ours={m.heldout} base={base.heldout} baseLabel={base.label ?? t('mc.base')} note={t('mc.heldoutNote')} />
            </div>
            <dl className={local.minis}>
              <div>
                <dt>{t('mc.speed')}</dt>
                <dd>{m.median_ms ? `${Math.round(m.median_ms)} ms` : '—'}</dd>
              </div>
              <div>
                <dt>{t('mc.invalid')}</dt>
                <dd>{m.invalid_outputs ?? '—'}</dd>
              </div>
              <div>
                <dt>{t('mc.cost')}</dt>
                <dd>{t('mc.costValue')}</dd>
              </div>
            </dl>
            {!!m.top_confusions?.length && (
              <div className={local.confusions}>
                <h3>{t('mc.confusions')}</h3>
                <ul>
                  {m.top_confusions.map(([truth, guess, n]) => (
                    <li key={`${truth}-${guess}`}>
                      <span>{human(truth)}</span>
                      <span aria-hidden="true">→</span>
                      <span>{human(guess)}</span>
                      <b>×{n}</b>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <div className={local.twoUp}>
            <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 6 } as CSSProperties}>
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('mc.loop')}</h2>
                  <p className={styles.panelSub}>{t('mc.loopSub')}</p>
                </div>
              </div>
              <ol className={local.loop}>
                <li>
                  <b>{card!.corrections.total}</b>
                  <span>{t('mc.loopCollected')}</span>
                </li>
                <li>
                  <b>{card!.corrections.since_last_training}</b>
                  <span>{t('mc.loopWaiting')}</span>
                </li>
                <li>
                  <b>{t('mc.loopWhen')}</b>
                  <span>{t('mc.loopGate')}</span>
                </li>
              </ol>
            </section>

            <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('mc.deploy')}</h2>
                  <p className={styles.panelSub}>{t('mc.deploySub')}</p>
                </div>
                <span className={`${local.mode} ${local[`mode_${dep?.mode ?? 'off'}`]}`}>{t(`mc.mode_${dep?.mode ?? 'off'}`)}</span>
              </div>
              <dl className={local.deploy}>
                <div>
                  <dt>{t('mc.active')}</dt>
                  <dd><code>{dep?.active_revision?.slice(0, 10) ?? t('mc.latest')}</code></dd>
                </div>
                <div>
                  <dt>{t('mc.candidate')}</dt>
                  <dd>{dep?.candidate_revision ? <code>{dep.candidate_revision.slice(0, 10)}</code> : t('mc.none')}</dd>
                </div>
                {dep?.mode === 'canary' && (
                  <div>
                    <dt>{t('mc.canary')}</dt>
                    <dd>{dep.canary_percent}%</dd>
                  </div>
                )}
                {dep?.mode !== 'off' && (
                  <div>
                    <dt>{t('mc.agreement')}</dt>
                    <dd>{card?.shadow?.compared ? `${pct(card.shadow.agreement ?? undefined)} · ${t('mc.compared', { count: card.shadow.compared })}` : '—'}</dd>
                  </div>
                )}
              </dl>
              <p className={styles.muted}>{t('mc.rollback')}</p>
            </section>
          </div>

          <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 8 } as CSSProperties}>
            <div className={styles.panelHead}>
              <h2>{t('mc.history')}</h2>
            </div>
            <ol className={local.history}>
              {card!.versions.map((v) => (
                <li key={v.version}>
                  <span className={local.dot} aria-hidden="true" />
                  <div>
                    <div className={local.historyHead}>
                      <strong>{v.version}</strong>
                      <time dateTime={v.trained_at}>{date.format(new Date(v.trained_at))}</time>
                      {v.revision && <code>{v.revision.slice(0, 10)}</code>}
                    </div>
                    <p>
                      {t('mc.historyLine', { golden: pct(v.metrics.golden), heldout: pct(v.metrics.heldout) })}
                      {v.notes ? ` ${v.notes}` : ''}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </div>
  )
}
