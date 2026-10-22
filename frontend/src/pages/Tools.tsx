import type { CSSProperties, ReactNode } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import PersonaFigure from '../components/PersonaFigure'
import SideDrawer from '../components/SideDrawer'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './Tools.module.css'
import Select from '../components/Select'

const CAPABILITIES = ['feasibility', 'personas', 'image'] as const
type Capability = (typeof CAPABILITIES)[number]
type RunStatus = 'pending' | 'running' | 'completed' | 'failed'

interface Run {
  id: string
  capability: string
  status: RunStatus
  params: Record<string, unknown>
  result: unknown
  error: string | null
  created_at: string
}

const CAP_META: Record<Capability, { title: string; desc: string; icon: ReactNode }> = {
  feasibility: {
    title: 'tl.capFeasibility',
    desc: 'tl.capFeasibilityDesc',
    icon: <path d="M4 19V5M4 19h16M8 15l4-4 3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />,
  },
  personas: {
    title: 'tl.capPersonas',
    desc: 'tl.capPersonasDesc',
    icon: (
      <>
        <circle cx="9" cy="8" r="3.5" stroke="currentColor" strokeWidth="2" />
        <path d="M2.5 20c1-3.5 3.6-5.5 6.5-5.5s5.5 2 6.5 5.5M16 4.5a3.5 3.5 0 0 1 0 7M18 14.8c1.8.7 3 2.5 3.5 5.2" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  },
  image: {
    title: 'tl.capImage',
    desc: 'tl.capImageDesc',
    icon: (
      <>
        <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
        <path d="M3 15l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <circle cx="15.5" cy="8.5" r="1.5" fill="currentColor" />
      </>
    ),
  },
}

const PROGRESS: { key: string; label: string }[] = [
  { key: 'dispatched', label: 'tl.stepDispatch' },
  { key: 'pending', label: 'tl.stQueued' },
  { key: 'running', label: 'tl.stRunning' },
  { key: 'completed', label: 'tl.stDone' },
]

const isCapability = (c: string): c is Capability => (CAPABILITIES as readonly string[]).includes(c)
const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** Drops huge base64 blobs from the raw JSON view. */
function compact(value: unknown): unknown {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, k === 'image_base64' ? `<${String(v).length} chars>` : v]),
    )
  }
  return value
}

function ResultView({ capability, result }: { capability: string; result: unknown }) {
  const { t } = useTranslation()
  const r = result as Record<string, unknown> | Record<string, unknown>[] | null

  if (capability === 'image' && r && !Array.isArray(r) && typeof r.image_base64 === 'string') {
    const src = `data:image/png;base64,${r.image_base64}`
    return (
      <div className={local.imageResult}>
        <img src={src} alt="" />
        <a className={`${styles.btn} ${styles.ghost}`} href={src} download="marketingos-ad.png">
          {t('tl.download')}
        </a>
      </div>
    )
  }

  if (capability === 'feasibility' && r && !Array.isArray(r) && typeof r.score === 'number') {
    const signals = (r.signals ?? {}) as Record<string, Record<string, unknown>>
    return (
      <div className={local.feas}>
        <div className={local.scoreBlock}>
          <span>{t('tl.score')}</span>
          <strong>{r.score}</strong>
          <div className={styles.track}>
            <span className={styles.fill} style={{ width: `${Math.min(100, r.score)}%` }} />
          </div>
        </div>
        {typeof r.rationale === 'string' && <p className={local.rationale}>{r.rationale}</p>}
        {Object.keys(signals).length > 0 && (
          <div>
            <h4 className={local.subhead}>{t('tl.signals')}</h4>
            <div className={local.signals}>
              {Object.entries(signals).map(([name, sig]) => (
                <div key={name} className={local.signal}>
                  <strong>{humanize(name)}</strong>
                  {Object.entries(sig ?? {})
                    .filter(([, v]) => ['number', 'string', 'boolean'].includes(typeof v) && String(v).length < 60)
                    .slice(0, 4)
                    .map(([k, v]) => (
                      <span key={k}>
                        {humanize(k)}: <b>{typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v)}</b>
                      </span>
                    ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  if (capability === 'personas' && Array.isArray(r)) {
    return (
      <div className={local.personas}>
        {r.map((p, i) => (
          <article key={i} className={local.persona} style={{ '--i': i } as CSSProperties}>
            <PersonaFigure archetype={p.archetype} gender={p.gender} name={p.name} demographics={p.demographics} psychographics={p.psychographics} size="lg" />
            <strong>{String(p.name ?? `#${i + 1}`)}</strong>
            {['demographics', 'psychographics'].map((k) => (p[k] ? <p key={k}>{String(p[k])}</p> : null))}
            <div className={local.personaChips}>
              {['age_bracket', 'income_tier', 'channel_fit'].map((k) =>
                p[k] ? (
                  <span key={k} className={styles.chip}>
                    {String(p[k])}
                  </span>
                ) : null,
              )}
            </div>
            {p.messaging_angle ? <p className={local.angle}>“{String(p.messaging_angle)}”</p> : null}
          </article>
        ))}
      </div>
    )
  }

  return <pre className={styles.code}>{JSON.stringify(compact(result), null, 2)}</pre>
}

export default function Tools() {
  const { t, i18n } = useTranslation()
  const [capability, setCapability] = useState<Capability>('feasibility')
  const [idea, setIdea] = useState('')
  const [prompt, setPrompt] = useState('')
  const [language, setLanguage] = useState('en')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)

  const loadRuns = useCallback(async () => {
    const { data } = await supabase
      .from('capability_runs')
      .select('id,capability,status,params,result,error,created_at')
      .order('created_at', { ascending: false })
      .limit(8)
    setRuns((data as Run[]) ?? [])
  }, [])

  useEffect(() => {
    loadRuns()
  }, [loadRuns])

  // Every status change on this user's runs (RLS-scoped) arrives live.
  useEffect(() => {
    const channel = supabase
      .channel('capability-runs')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'capability_runs' }, () => loadRuns())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [loadRuns])

  async function submit() {
    const value = capability === 'image' ? prompt.trim() : idea.trim()
    if (!value || submitting) return
    setSubmitting(true)
    setError(null)
    const params = capability === 'image' ? { prompt: value } : { idea: value, target_language: language }
    const { data, error: invokeError } = await supabase.functions.invoke('trigger-capability-run', {
      body: { capability, params },
    })
    setSubmitting(false)
    if (invokeError) {
      setError(t('tl.failedDispatch', { message: invokeError.message }))
      return
    }
    setActiveId(data.run_id)
    await loadRuns()
  }

  function reuse(run: Run) {
    if (!isCapability(run.capability)) return
    setCapability(run.capability)
    if (typeof run.params.idea === 'string') setIdea(run.params.idea)
    if (typeof run.params.prompt === 'string') setPrompt(run.params.prompt)
    if (typeof run.params.target_language === 'string') setLanguage(run.params.target_language)
    setActiveId(run.id)
  }

  const active = runs.find((r) => r.id === activeId) ?? null
  const progressIndex = !active ? (submitting ? 0 : -1) : active.status === 'pending' ? 1 : active.status === 'running' ? 2 : 3
  const failed = active?.status === 'failed'
  const inputValue = capability === 'image' ? prompt : idea
  const relTime = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' })
  const ago = (iso: string) => {
    const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
    return Math.abs(mins) < 60 ? relTime.format(mins, 'minute') : Math.abs(mins) < 1440 ? relTime.format(Math.round(mins / 60), 'hour') : relTime.format(Math.round(mins / 1440), 'day')
  }

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('tl.title')}</span>
          <h1 className={styles.title}>{t('tools.title')}</h1>
          <p className={styles.subtitle}>{t('tools.subtitle')}</p>
        </div>
      </header>

      <div className={local.caps} role="radiogroup" aria-label={t('tl.title')}>
        {CAPABILITIES.map((c, i) => (
          <button
            key={c}
            type="button"
            role="radio"
            aria-checked={capability === c}
            className={`${local.cap} ${capability === c ? local.capActive : ''} ${styles.enter}`}
            style={{ '--i': i + 1 } as CSSProperties}
            onClick={() => setCapability(c)}
          >
            <span className={local.capIcon}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                {CAP_META[c].icon}
              </svg>
            </span>
            <strong>{t(CAP_META[c].title)}</strong>
            <span>{t(CAP_META[c].desc)}</span>
            <span className={local.capCheck} aria-hidden="true" />
          </button>
        ))}
      </div>

      <div className={styles.stack}>
          <section className={`${styles.panel} ${local.form} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
            <label className={styles.field}>
              <span>{capability === 'image' ? t('tl.inputPrompt') : t('tl.inputIdea')}</span>
              <textarea
                className={styles.textarea}
                rows={3}
                value={inputValue}
                onChange={(e) => (capability === 'image' ? setPrompt(e.target.value) : setIdea(e.target.value))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault()
                    submit()
                  }
                }}
                placeholder={capability === 'image' ? t('tools.imagePromptPlaceholder') : t('tools.ideaPlaceholder')}
              />
            </label>
            <div className={local.formFoot}>
              {capability !== 'image' ? (
                <label className={local.lang}>
                  <span>{t('cd.language')}</span>
                  <Select
                    aria-label={t('cd.language')}
                    value={language}
                    onChange={setLanguage}
                    options={CAMPAIGN_LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
                  />
                </label>
              ) : (
                <span />
              )}
              <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={submit} disabled={submitting || !inputValue.trim()}>
                {submitting && <span className={styles.spinner} aria-hidden="true" />}
                {submitting ? t('tools.dispatching') : t('tools.run')}
                {!submitting && (
                  <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </div>
            {error && (
              <p className={`${styles.toast} ${styles.toastError}`} role="alert">
                {error}
              </p>
            )}
          </section>

          <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties} aria-live="polite">
            <div className={styles.panelHead}>
              <h2>{t('tl.resultTitle')}</h2>
              {active && <span className={styles.chip}>{t(CAP_META[isCapability(active.capability) ? active.capability : 'feasibility'].title)}</span>}
            </div>

            {progressIndex >= 0 && (
              <ol className={`${local.progress} ${failed ? local.progressFailed : ''}`}>
                {PROGRESS.map((p, i) => {
                  const done = i < progressIndex || (i === progressIndex && active?.status === 'completed')
                  const current = i === progressIndex && !done
                  return (
                    <li key={p.key} className={done ? local.pDone : current ? local.pCurrent : ''}>
                      <span className={local.pDot} aria-hidden="true" />
                      {failed && i === PROGRESS.length - 1 ? t('tl.stFailed') : t(p.label)}
                    </li>
                  )
                })}
              </ol>
            )}

            {!active && !submitting && <p className={styles.muted}>{t('tl.emptyResult')}</p>}
            {active && (active.status === 'pending' || active.status === 'running') && (
              <div className={local.waiting}>
                <span className={styles.skeleton} style={{ height: 18, width: '40%' }} />
                <span className={styles.skeleton} style={{ height: 14 }} />
                <span className={styles.skeleton} style={{ height: 14, width: '85%' }} />
                <p className={styles.muted}>{t('tl.etaHint')}</p>
              </div>
            )}
            {active?.status === 'failed' && (
              <p className={`${styles.toast} ${styles.toastError}`} role="alert">
                {active.error ?? t('tl.stFailed')}
              </p>
            )}
            {active?.status === 'completed' && (
              <div className={local.result}>
                <ResultView capability={active.capability} result={active.result} />
                <details className={styles.details}>
                  <summary>{t('tl.rawJson')}</summary>
                  <pre className={styles.code}>{JSON.stringify(compact(active.result), null, 2)}</pre>
                </details>
              </div>
            )}
          </section>
      </div>

      <SideDrawer
        side="right"
        label={t('tl.historyTitle')}
        count={runs.length}
        busy={runs.some((r) => r.status === 'pending' || r.status === 'running')}
        open={historyOpen}
        onOpenChange={setHistoryOpen}
      >
          {runs.length === 0 ? (
            <p className={styles.muted}>{t('tl.historyEmpty')}</p>
          ) : (
            <ul className={local.history}>
              {runs.map((r) => {
                const input = String(r.params.idea ?? r.params.prompt ?? '')
                return (
                  <li key={r.id}>
                    <button type="button" className={`${local.historyItem} ${r.id === activeId ? local.historyActive : ''}`} onClick={() => {
                        reuse(r)
                        setHistoryOpen(false)
                      }}>
                      <span className={`${local.hDot} ${local[`h_${r.status}`]}`} aria-hidden="true" />
                      <span className={local.hBody}>
                        <strong>{isCapability(r.capability) ? t(CAP_META[r.capability].title) : r.capability}</strong>
                        <span>{input || '—'}</span>
                      </span>
                      <time dateTime={r.created_at}>{ago(r.created_at)}</time>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
      </SideDrawer>
    </div>
  )
}
