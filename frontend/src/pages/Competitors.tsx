import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Select from '../components/Select'
import { FORECAST_MODEL } from '../lib/forecastModel'
import { usePageLoading } from '../lib/loading'
import { toastFailure, toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import type {
  Competitor, CompetitorEvent, CompetitorInsight, CompetitorPrediction, CompetitorSource, SourceKind,
} from '../lib/types'
import { useOrg } from '../lib/useOrg'
import { useWorkerRun } from '../lib/workerRun'
import styles from '../styles/app.module.css'
import local from './Competitors.module.css'

const SOURCE_KINDS: SourceKind[] = ['webpage', 'rss', 'news', 'bluesky']
const pct = (x: number, digits = 0) => `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x * 100).toFixed(digits)}%`

function ago(iso: string | null | undefined, lang: string): string {
  if (!iso) return '—'
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  const fmt = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  if (Math.abs(mins) < 60) return fmt.format(mins, 'minute')
  if (Math.abs(mins) < 1440) return fmt.format(Math.round(mins / 60), 'hour')
  return fmt.format(Math.round(mins / 1440), 'day')
}

function AddCompetitor({ orgId, onDone }: { orgId: string; onDone: (id: string) => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState('')
  const [website, setWebsite] = useState('')
  const [names, setNames] = useState('')
  const [market, setMarket] = useState('')
  const [busy, setBusy] = useState(false)
  const validSite = !website.trim() || /^https?:\/\/\S+\.\S+/.test(website.trim())

  async function save() {
    setBusy(true)
    const keywords = names.split(',').map((s) => s.trim()).filter(Boolean)
    const { data, error } = await supabase.rpc('upsert_competitor', {
      p_org: orgId, p_name: name.trim(), p_website: website.trim() || null,
      p_keywords: keywords.length ? keywords : null, p_category_keyword: market.trim() || null, p_markets: null,
    })
    if (!error && website.trim()) {
      await supabase.rpc('add_competitor_source', { p_competitor: data, p_kind: 'webpage', p_locator: website.trim(), p_approve: false })
    }
    if (!error) {
      await supabase.rpc('add_competitor_source', { p_competitor: data, p_kind: 'news', p_locator: name.trim(), p_approve: false })
    }
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('ci.addedToast', { name: name.trim() }))
    setName('')
    setWebsite('')
    setNames('')
    setMarket('')
    onDone(data as string)
  }

  return (
    <section className={`${styles.panel} ${local.add}`} data-testid="add-competitor">
      <div className={styles.panelHead}>
        <div>
          <h2>{t('ci.addTitle')}</h2>
          <p className={styles.panelSub}>{t('ci.addSub')}</p>
        </div>
      </div>
      <div className={local.addGrid}>
        <label className={styles.field}>
          <span>{t('ci.name')}</span>
          <input className={styles.input} value={name} onChange={(e) => setName(e.target.value)} placeholder="BrewCo" />
        </label>
        <label className={styles.field}>
          <span>{t('ci.website')}</span>
          <input className={styles.input} value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://brewco.example/pricing" />
        </label>
        <label className={styles.field}>
          <span>{t('ci.newsNames')}</span>
          <input className={styles.input} value={names} onChange={(e) => setNames(e.target.value)} placeholder={t('ci.newsNamesPlaceholder')} />
        </label>
        <label className={styles.field}>
          <span>{t('ci.market')}</span>
          <input className={styles.input} value={market} onChange={(e) => setMarket(e.target.value)} placeholder={t('ci.marketPlaceholder')} />
        </label>
      </div>
      <p className={local.muted}>{t('ci.addNote')}</p>
      <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy || !name.trim() || !validSite} onClick={save}>
        {t('ci.add')}
      </button>
    </section>
  )
}

function Sources({ competitor, sources, canManage, onDone }: {
  competitor: Competitor
  sources: CompetitorSource[]
  canManage: boolean
  onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const [kind, setKind] = useState<SourceKind>('rss')
  const [locator, setLocator] = useState('')
  const [busy, setBusy] = useState(false)
  const [scanning, scan] = useWorkerRun((ok, error) => {
    if (ok) toast.success(t('ci.scanDone'))
    else toast.error(error || t('ci.scanFailed'))
    onDone()
  })

  async function approve(s: CompetitorSource, value: boolean) {
    const { error } = await supabase.rpc('approve_competitor_source', { p_source: s.id, p_approved: value })
    if (toastFailure(t, error)) return
    onDone()
  }

  async function add() {
    setBusy(true)
    const { error } = await supabase.rpc('add_competitor_source', { p_competitor: competitor.id, p_kind: kind, p_locator: locator.trim(), p_approve: false })
    setBusy(false)
    if (toastFailure(t, error)) return
    setLocator('')
    onDone()
  }

  async function scanNow() {
    const error = await scan('competitor_scan', { competitor_id: competitor.id })
    if (error) toast.error(error)
    else toast.success(t('ci.scanStarted'))
  }

  return (
    <section className={styles.panel} data-testid="ci-sources">
      <div className={styles.panelHead}>
        <div>
          <h2>{t('ci.sourcesTitle')}</h2>
          <p className={styles.panelSub}>{t('ci.sourcesSub')}</p>
        </div>
        {canManage && (
          <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={scanning || !sources.some((s) => s.approved)} onClick={scanNow}>
            {scanning ? t('ci.scanning') : t('ci.scanNow')}
          </button>
        )}
      </div>
      <ul className={local.sources}>
        {sources.map((s) => (
          <li key={s.id} className={local.source}>
            <div className={local.sourceMain}>
              <span className={local.kind}>{t(`ci.kind.${s.kind}`)}</span>
              <code className={local.locator}>{s.locator}</code>
            </div>
            <div className={local.sourceMeta}>
              <span className={`${local.status} ${local[`st_${s.status}`]}`}>{s.approved ? t(`ci.status.${s.status}`) : t('ci.notApproved')}</span>
              {s.approved && s.last_ok_at && <small>{t('ci.lastOk', { when: ago(s.last_ok_at, i18n.language) })}</small>}
              {s.approved && s.status !== 'ok' && s.last_error && <small className={local.error}>{s.last_error}</small>}
            </div>
            {canManage && (
              <button type="button" className={`${styles.btn} ${s.approved ? styles.ghost : styles.primary} ${local.small}`} onClick={() => approve(s, !s.approved)}>
                {s.approved ? t('ci.pause') : t('ci.approve')}
              </button>
            )}
          </li>
        ))}
        {!sources.length && <li className={local.muted}>{t('ci.noSources')}</li>}
      </ul>
      {canManage && (
        <div className={local.addSource}>
          <Select aria-label={t('ci.sourceKind')} value={kind} onChange={setKind} options={SOURCE_KINDS.map((k) => ({ value: k, label: t(`ci.kind.${k}`) }))} />
          <input className={styles.input} value={locator} onChange={(e) => setLocator(e.target.value)} placeholder={t(`ci.locatorHint.${kind}`)} aria-label={t('ci.locator')} />
          <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy || !locator.trim()} onClick={add}>{t('ci.addSource')}</button>
        </div>
      )}
      <p className={local.muted}>{t('ci.permitted')}</p>
    </section>
  )
}

function Quote({ label, text }: { label: string; text: unknown }) {
  if (!text || (Array.isArray(text) && !text.length)) return null
  return (
    <p className={local.quote}>
      <span>{label}</span> {Array.isArray(text) ? text.join(', ') : `“${String(text)}”`}
    </p>
  )
}

function InsightCard({ insight, canManage, onDone }: { insight: CompetitorInsight; canManage: boolean; onDone: () => void }) {
  const { t } = useTranslation()
  const [note, setNote] = useState('')

  async function decide(status: 'acted' | 'dismissed' | 'open') {
    const { error } = await supabase.rpc('decide_competitor_insight', { p_insight: insight.id, p_status: status, p_note: note.trim() || null })
    if (toastFailure(t, error)) return
    onDone()
  }

  const campaigns = insight.relevance.live_campaigns ?? []
  return (
    <div className={local.insight}>
      <div className={local.insightHead}>
        <span className={local.recommend}>{t(`ci.action.${insight.recommendation}`)}</span>
        <small>{t('ci.confidence', { pct: Math.round(insight.confidence * 100) })}</small>
        {insight.status !== 'open' && <span className={local.done}>{t(`ci.decided.${insight.status}`)}{insight.note ? `: ${insight.note}` : ''}</span>}
      </div>
      <p className={local.muted}>
        {campaigns.length ? t('ci.affects', { ideas: campaigns.map((c) => `“${c.idea}”`).join(', ') }) : t('ci.affectsNone')}
      </p>
      <ul className={local.options}>
        {insight.options.map((o) => (
          <li key={o.action} className={o.recommended ? local.optionPicked : ''}>
            <strong>{t(`ci.action.${o.action}`)}</strong>
            <span>{o.reasons.map((r) => t(`ci.reason.${r}`)).join(' ')}</span>
          </li>
        ))}
      </ul>
      <details className={local.inferred}>
        <summary>{t('ci.inferredTitle')} <em>{t('ci.inferredTag')}</em></summary>
        <ul>
          {insight.explanations.map((h, i) => (
            <li key={i}>
              {h.hypothesis ?? t(`ci.hypothesis.${h.hypothesis_code}`)}
              {h.would_confirm && <small>{t('ci.wouldConfirm')}: {h.would_confirm}</small>}
              {h.would_refute && <small>{t('ci.wouldRefute')}: {h.would_refute}</small>}
            </li>
          ))}
        </ul>
      </details>
      {canManage && insight.status === 'open' && (
        <div className={local.decide}>
          <input className={styles.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('ci.notePlaceholder')} aria-label={t('ci.note')} />
          <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={() => decide('acted')}>{t('ci.markActed')}</button>
          <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={() => decide('dismissed')}>{t('ci.dismiss')}</button>
        </div>
      )}
    </div>
  )
}

function Forecast({ p }: { p: CompetitorPrediction }) {
  const { t, i18n } = useTranslation()
  const date = new Date(p.resolve_after).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short' })
  return (
    <div className={local.forecast} data-testid="ci-forecast">
      <span className={local.forecastLabel}>{t('ci.forecast', { keyword: p.keyword, days: p.horizon_days })}</span>
      <strong>{pct(p.predicted_change, 1)}</strong>
      <small>{t('ci.forecastInterval', { level: Math.round(p.interval_level * 100), lo: pct(p.interval_low), hi: pct(p.interval_high) })}</small>
      {p.status === 'pending' && <small>{t('ci.checkOn', { date })}</small>}
      {p.status === 'resolved' && p.observed_change !== null && (
        <small className={p.inside_interval ? local.hit : local.miss}>
          {t('ci.observedChange', { change: pct(p.observed_change, 1) })} {p.inside_interval ? t('ci.inside') : t('ci.outside')}
          {p.materialized !== null && ` ${p.materialized ? t('ci.materialized') : t('ci.notMaterialized')}`}
        </small>
      )}
      {p.status === 'unresolvable' && <small>{t('ci.unresolvable')}</small>}
    </div>
  )
}

/** Competitor intelligence: who we watch, through which approved sources, what they did, and what we could do about it. */
export default function Competitors() {
  const { t, i18n } = useTranslation()
  const { active, can } = useOrg()
  const [competitors, setCompetitors] = useState<Competitor[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [events, setEvents] = useState<CompetitorEvent[]>([])
  const [insights, setInsights] = useState<CompetitorInsight[]>([])
  const [predictions, setPredictions] = useState<CompetitorPrediction[]>([])
  const [loaded, setLoaded] = useState(false)
  usePageLoading(!loaded)
  const canManage = !!active && (can('create', active.id) || can('manage', active.id))

  const load = useCallback(async () => {
    if (!active) return
    const { data, error } = await supabase.from('competitors')
      .select('id,org_id,name,website,keywords,category_keyword,markets,created_at,competitor_sources(id,kind,locator,approved,status,last_fetched_at,last_ok_at,last_error)')
      .eq('org_id', active.id).is('archived_at', null).order('name')
    setLoaded(true)
    if (toastLoadError(t, error, () => load())) return
    const list = (data as Competitor[]) ?? []
    setCompetitors(list)
    setSelected((s) => (s && list.some((c) => c.id === s) ? s : list[0]?.id ?? null))
  }, [active, t])

  const loadSignals = useCallback(async () => {
    if (!selected) return
    const [{ data: ev }, { data: ins }, { data: pr }] = await Promise.all([
      supabase.from('competitor_events').select('*').eq('competitor_id', selected).order('observed_at', { ascending: false }).limit(60),
      supabase.from('competitor_insights').select('*').eq('competitor_id', selected),
      supabase.from('competitor_predictions').select('*').eq('competitor_id', selected).order('made_at', { ascending: false }),
    ])
    setEvents((ev as CompetitorEvent[]) ?? [])
    setInsights((ins as CompetitorInsight[]) ?? [])
    setPredictions((pr as CompetitorPrediction[]) ?? [])
  }, [selected])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadSignals() }, [loadSignals])

  const current = competitors.find((c) => c.id === selected) ?? null
  const sources = current?.competitor_sources ?? []
  const limitations = sources.filter((s) => s.approved && s.status !== 'ok' && s.status !== 'never')
  const insightOf = useMemo(() => new Map(insights.map((i) => [i.event_id, i])), [insights])
  const predictionOf = useMemo(() => new Map(predictions.filter((p) => p.event_id).map((p) => [p.event_id!, p])), [predictions])
  const resolved = predictions.filter((p) => p.status === 'resolved' && p.observed_change !== null)
  const reload = () => { load(); loadSignals() }

  async function archive() {
    if (!current) return
    const { error } = await supabase.rpc('archive_competitor', { p_competitor: current.id })
    if (toastFailure(t, error)) return
    toast.success(t('ci.archivedToast', { name: current.name }))
    load()
  }

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('ci.eyebrow')}</span>
          <h1 className={styles.title}>{t('ci.title')}</h1>
          <p className={styles.subtitle}>{t('ci.subtitle')}</p>
        </div>
      </header>

      {competitors.length > 0 && (
        <nav className={local.tabs} aria-label={t('ci.title')}>
          {competitors.map((c) => (
            <button key={c.id} type="button" className={`${local.tab} ${c.id === selected ? local.tabActive : ''}`} aria-pressed={c.id === selected} onClick={() => setSelected(c.id)}>
              {c.name}
            </button>
          ))}
        </nav>
      )}

      {current && (
        <>
          {limitations.length > 0 && (
            <section className={`${styles.panel} ${local.limits}`} role="status" data-testid="ci-limitations">
              <strong>{t('ci.limitsTitle')}</strong>
              <ul>
                {limitations.map((s) => (
                  <li key={s.id}>{t('ci.limitLine', { kind: t(`ci.kind.${s.kind}`), status: t(`ci.status.${s.status}`), when: ago(s.last_ok_at, i18n.language) })}</li>
                ))}
              </ul>
            </section>
          )}

          <section className={styles.panel} data-testid="ci-timeline">
            <div className={styles.panelHead}>
              <div>
                <h2>{t('ci.timelineTitle', { name: current.name })}</h2>
                <p className={styles.panelSub}>{t('ci.timelineSub')}</p>
              </div>
            </div>
            {!events.length && <p className={local.muted}>{sources.some((s) => s.approved) ? t('ci.noEvents') : t('ci.approveFirst')}</p>}
            <ol className={local.timeline}>
              {events.map((e) => {
                const ins = insightOf.get(e.id)
                const pred = predictionOf.get(e.id)
                const o = e.observed as Record<string, unknown>
                return (
                  <li key={e.id} className={local.event}>
                    <div className={local.eventHead}>
                      <span className={local.eventKind}>{t(`ci.event.${e.kind}`)}</span>
                      <span className={local.observedTag}>{t('ci.observedTag')}</span>
                      <time dateTime={e.published_at ?? e.observed_at}>{ago(e.published_at ?? e.observed_at, i18n.language)}</time>
                    </div>
                    <p className={local.summary}>{e.summary}</p>
                    <Quote label={t('ci.before')} text={o.before} />
                    <Quote label={t('ci.after')} text={o.after} />
                    <p className={local.sourceLine}>
                      {e.url ? <a href={e.url} target="_blank" rel="noopener noreferrer">{e.original_outlet ?? e.outlet ?? e.url}</a> : (e.outlet ?? '—')}
                      {e.reports > 1 && <> · {t('ci.reports', { count: e.reports, outlets: e.outlets.join(', ') })}</>}
                      {' · '}{t('ci.seen', { when: ago(e.observed_at, i18n.language) })}
                    </p>
                    {ins && <InsightCard insight={ins} canManage={canManage} onDone={loadSignals} />}
                    {pred && <Forecast p={pred} />}
                  </li>
                )
              })}
            </ol>
          </section>

          <div className={local.twoCol}>
            <Sources competitor={current} sources={sources} canManage={canManage} onDone={reload} />
            <section className={styles.panel} data-testid="ci-forecast-record">
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('ci.recordTitle')}</h2>
                  <p className={styles.panelSub}>{t('ci.recordSub', { keyword: current.category_keyword ?? '—' })}</p>
                </div>
              </div>
              <ul className={local.record}>
                <li>{t('ci.modelHeldOut', { n: FORECAST_MODEL.heldOutForecasts.toLocaleString(i18n.language), model: (FORECAST_MODEL.modelError * 100).toFixed(1), naive: (FORECAST_MODEL.naiveError * 100).toFixed(1), level: Math.round(FORECAST_MODEL.intervalLevel * 100), coverage: Math.round(FORECAST_MODEL.intervalCoverage * 100) })}</li>
                <li>
                  {resolved.length
                    ? t('ci.ownRecord', { count: resolved.length, inside: resolved.filter((p) => p.inside_interval).length, error: (resolved.reduce((s, p) => s + Math.abs((p.observed_change ?? 0) - p.predicted_change), 0) / resolved.length * 100).toFixed(1) })
                    : t('ci.ownRecordNone')}
                </li>
                {!current.category_keyword && <li>{t('ci.noMarket')}</li>}
              </ul>
              {canManage && (
                <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={archive}>{t('ci.archive')}</button>
              )}
            </section>
          </div>
        </>
      )}

      {loaded && !competitors.length && <p className={local.empty}>{t('ci.empty')}</p>}
      {canManage && active && <AddCompetitor orgId={active.id} onDone={(id) => { setSelected(id); load() }} />}
    </div>
  )
}
