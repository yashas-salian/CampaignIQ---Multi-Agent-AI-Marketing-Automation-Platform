import type { CSSProperties } from 'react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import PersonaStage from '../components/PersonaStage'
import PersonaChat from '../components/PersonaChat'
import { archetypeFor } from '../lib/archetypes'
import { CAP_META, CAPABILITIES, RUN_COLUMNS, isCapability, runInput, type Capability, type Run } from '../lib/capabilityRuns'
import SideDrawer from '../components/SideDrawer'
import { toast } from '../lib/toast'
import { toastLoadError } from '../lib/notify'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './Tools.module.css'
import Select from '../components/Select'
import { ProductFields } from '../components/ProductFields'
import DecisionCard from '../components/DecisionCard'
import CrashTestReport from '../components/CrashTestReport'
import type { CrashReport } from '../lib/types'
import type { CampaignDecision } from '../lib/types'
import { AD_TEMPLATES } from '../lib/adTemplates'
import { useSession } from '../lib/useAuth'

const PROGRESS: { key: string; label: string }[] = [
  { key: 'dispatched', label: 'tl.stepDispatch' },
  { key: 'pending', label: 'tl.stQueued' },
  { key: 'running', label: 'tl.stRunning' },
  { key: 'completed', label: 'tl.stDone' },
]

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

function ResultView({ capability, result, runId }: { capability: string; result: unknown; runId: string }) {
  const { t } = useTranslation()
  const [chatIndex, setChatIndex] = useState<number | null>(null)
  const r = result as Record<string, unknown> | Record<string, unknown>[] | null

  if (capability === 'image' && r && !Array.isArray(r) && typeof r.image_base64 === 'string') {
    const mime = typeof r.mime === 'string' ? r.mime : 'image/png'
    const src = `data:${mime};base64,${r.image_base64}`
    return (
      <div className={local.imageResult}>
        <img src={src} alt={typeof r.headline === 'string' ? r.headline : ''} />
        {typeof r.template === 'string' && r.template && <span className={styles.chip}>{t('product.template')}: {humanize(r.template)}</span>}
        {typeof r.copy_text === 'string' && r.copy_text && <p className={local.rationale}>{r.copy_text}</p>}
        <a className={`${styles.btn} ${styles.ghost}`} href={src} download={mime === 'image/jpeg' ? 'marketingos-ad.jpg' : 'marketingos-ad.png'}>
          {t('tl.download')}
        </a>
      </div>
    )
  }

  if (capability === 'crash_test' && r && !Array.isArray(r) && Array.isArray(r.findings)) {
    return <CrashTestReport report={r as unknown as CrashReport} />
  }

  if (capability === 'decision' && r && !Array.isArray(r) && typeof r.decision === 'string') {
    return <DecisionCard decision={r as unknown as CampaignDecision} />
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
          <div key={i} className={local.personaCol} style={{ '--i': i } as CSSProperties}>
          <PersonaStage archetype={p.archetype} gender={p.gender} name={p.name} demographics={p.demographics} psychographics={p.psychographics} />
          <article className={local.persona}>
            <span className={local.role}>{t(`persona.${archetypeFor(p.archetype, p.name, p.demographics)}`)}</span>
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
            <button type="button" className={local.interview} onClick={() => setChatIndex(i)}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" /><path d="M8 10h8M8 13h5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
              {t('chat.open', { name: String(p.name ?? '').split(' ')[0] })}
            </button>
          </article>
          </div>
        ))}
        {chatIndex !== null && r[chatIndex] && (
          <PersonaChat
            target={{ kind: 'run', runId, index: chatIndex }}
            persona={{ ...r[chatIndex], name: String(r[chatIndex].name ?? '') }}
            onClose={() => setChatIndex(null)}
          />
        )}
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
  // The ad image is built around the user's product photo (src/tools/ad_templates.py).
  const [productPhoto, setProductPhoto] = useState<File | null>(null)
  const [tagline, setTagline] = useState('')
  const [template, setTemplate] = useState('')
  const { session } = useSession()
  // The crash test's input: the ad itself, next to what's being advertised (the idea box).
  const [adCopy, setAdCopy] = useState('')
  const [adHeadline, setAdHeadline] = useState('')
  const [adCta, setAdCta] = useState('')
  const [language, setLanguage] = useState('en')
  const [submitting, setSubmitting] = useState(false)
  const [activeId, setActiveId] = useState<string | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [params, setParams] = useSearchParams()
  const [opened, setOpened] = useState<Run | null>(null)

  const loadRuns = useCallback(async () => {
    const { data, error } = await supabase
      .from('capability_runs')
      .select(RUN_COLUMNS)
      // Only Tools runs: campaign jobs (Gate 2's "New picture") share the table.
      .in('capability', [...CAPABILITIES])
      .order('created_at', { ascending: false })
      .limit(8)
    if (toastLoadError(t, error, () => loadRuns())) return
    setRuns((data as Run[]) ?? [])
  }, [t])

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
    if (!value || submitting || (capability === 'image' && !productPhoto)) return
    setSubmitting(true)
    if (capability === 'crash_test' && !adCopy.trim()) {
      setSubmitting(false)
      return
    }
    let params: Record<string, unknown> =
      capability === 'crash_test'
        ? { idea: value, copy: adCopy.trim(), headline: adHeadline.trim(), cta: adCta.trim(), target_language: language }
        : { idea: value, target_language: language }
    if (capability === 'image' && productPhoto) {
      // The photo goes up first, into the user's own folder; the run gets its path.
      const ext = productPhoto.type === 'image/png' ? 'png' : productPhoto.type === 'image/webp' ? 'webp' : 'jpg'
      const path = `${session?.user.id}/${crypto.randomUUID()}.${ext}`
      const upload = await supabase.storage.from('product-photos').upload(path, productPhoto, { contentType: productPhoto.type })
      if (upload.error || !session?.user.id) {
        setSubmitting(false)
        toast.error(t('product.uploadFailed', { message: upload.error?.message ?? 'no session' }))
        return
      }
      params = { prompt: value, product_image_path: path, tagline: tagline.trim(), template, target_language: language }
    }
    const { data, error: invokeError } = await supabase.functions.invoke('trigger-capability-run', {
      body: { capability, params },
    })
    setSubmitting(false)
    if (invokeError) {
      toast.error(t('tl.failedDispatch', { message: invokeError.message }))
      return
    }
    setActiveId(data.run_id)
    // The run is on its way: clear the box for the next one (the input stays visible in history).
    if (capability === 'image') setPrompt('')
    else setIdea('')
    await loadRuns()
  }

  // Arriving from Tools history with ?run=<id>: show that run and its inputs.
  const wantedRun = params.get('run')
  useEffect(() => {
    if (!wantedRun) return
    supabase
      .from('capability_runs')
      .select(RUN_COLUMNS)
      .eq('id', wantedRun)
      .maybeSingle()
      .then(({ data, error }) => {
        if (toastLoadError(t, error, () => setParams({ run: wantedRun }))) return
        if (data) {
          setOpened(data as Run)
          reuse(data as Run)
        }
        setParams({}, { replace: true })
      })
  }, [wantedRun, t, setParams])

  function reuse(run: Run) {
    if (!isCapability(run.capability)) return
    setCapability(run.capability)
    if (typeof run.params.idea === 'string') setIdea(run.params.idea)
    if (typeof run.params.prompt === 'string') setPrompt(run.params.prompt)
    if (typeof run.params.target_language === 'string') setLanguage(run.params.target_language)
    if (typeof run.params.tagline === 'string') setTagline(run.params.tagline)
    if (typeof run.params.template === 'string') setTemplate(run.params.template)
    if (typeof run.params.copy === 'string') setAdCopy(run.params.copy)
    if (typeof run.params.headline === 'string') setAdHeadline(run.params.headline)
    if (typeof run.params.cta === 'string') setAdCta(run.params.cta)
    setActiveId(run.id)
  }

  const active = runs.find((r) => r.id === activeId) ?? (opened?.id === activeId ? opened : null)
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
            {capability === 'crash_test' && (
              <div className={local.adFields}>
                <label className={styles.field}>
                  <span>{t('crash.toolCopy')}</span>
                  <textarea className={styles.textarea} rows={3} value={adCopy} onChange={(e) => setAdCopy(e.target.value)} placeholder={t('crash.toolCopyPlaceholder')} />
                </label>
                <div className={local.adRow}>
                  <label className={styles.field}>
                    <span>{t('crash.toolHeadline')}</span>
                    <input className={styles.input} value={adHeadline} onChange={(e) => setAdHeadline(e.target.value)} />
                  </label>
                  <label className={styles.field}>
                    <span>{t('crash.button')}</span>
                    <input className={styles.input} value={adCta} onChange={(e) => setAdCta(e.target.value)} />
                  </label>
                </div>
              </div>
            )}
            {capability === 'image' && (
              <ProductFields
                photo={productPhoto}
                onPhoto={setProductPhoto}
                tagline={tagline}
                onTagline={setTagline}
                extra={
                  <label className={local.templatePick}>
                    <span>{t('product.template')}</span>
                    <Select
                      aria-label={t('product.template')}
                      value={template}
                      onChange={setTemplate}
                      options={[{ value: '', label: t('tl.templateAuto') }, ...AD_TEMPLATES.map((id) => ({ value: id, label: humanize(id) }))]}
                    />
                  </label>
                }
              />
            )}
            <div className={local.formFoot}>
              <label className={local.lang}>
                <span>{t('cd.language')}</span>
                <Select
                  aria-label={t('cd.language')}
                  value={language}
                  onChange={setLanguage}
                  options={CAMPAIGN_LANGUAGES.map((l) => ({ value: l.code, label: l.label }))}
                />
              </label>
              <button
                type="button"
                className={`${styles.btn} ${styles.primary}`}
                onClick={submit}
                disabled={submitting || !inputValue.trim() || (capability === 'image' && !productPhoto) || (capability === 'crash_test' && !adCopy.trim())}
                title={capability === 'image' && !productPhoto ? t('product.photoNeeded') : undefined}
              >
                {submitting && <span className={styles.spinner} aria-hidden="true" />}
                {submitting ? t('tools.dispatching') : t('tools.run')}
                {!submitting && (
                  <svg className={styles.arrow} viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path d="M5 12h14M13 6l6 6-6 6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </button>
            </div>
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
                <ResultView capability={active.capability} result={active.result} runId={active.id} />
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
                const input = runInput(r)
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
          <Link to="/tools/history" className={`${local.allHistory} link-wipe`} onClick={() => setHistoryOpen(false)}>
            {t('hist.seeAll')} →
          </Link>
      </SideDrawer>
    </div>
  )
}
