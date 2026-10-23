import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import Select from '../components/Select'
import { CAP_META, CAPABILITIES, RUN_COLUMNS, isCapability, runInput, type Run, type RunStatus } from '../lib/capabilityRuns'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { usePageLoading } from '../lib/loading'
import { toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './ToolsHistory.module.css'

const LIMIT = 1000 // a person's own runs; plenty, and the page says so if it's reached
const PAGE = 30
type When = 'all' | 'today' | '7d' | '30d' | 'month' | 'year' | 'custom'
type StatusFilter = 'all' | 'completed' | 'failed' | 'active'

const STATUS_LABEL: Record<RunStatus, string> = {
  completed: 'tl.stDone',
  failed: 'tl.stFailed',
  running: 'tl.stRunning',
  pending: 'tl.stQueued',
}

/** One line that says what a run produced. */
function summary(run: Run, t: (k: string, o?: Record<string, unknown>) => string) {
  if (run.status === 'failed') return run.error?.split('\n')[0] ?? t('tl.stFailed')
  if (run.status !== 'completed') return t(STATUS_LABEL[run.status])
  const r = run.result as Record<string, unknown> | unknown[] | null
  if (run.capability === 'feasibility' && r && !Array.isArray(r) && typeof r.score === 'number') return t('hist.score', { score: r.score })
  if (run.capability === 'personas' && Array.isArray(r)) {
    const names = r.map((p) => String((p as Record<string, unknown>).name ?? '')).filter(Boolean)
    return t('hist.personas', { names: names.join(', ') })
  }
  if (run.capability === 'image') return t('hist.imageMade')
  return t('tl.stDone')
}

/** Everything searchable about a run, lower-cased once. */
function haystack(run: Run, t: (k: string) => string) {
  const lang = CAMPAIGN_LANGUAGES.find((l) => l.code === run.params.target_language)?.label ?? ''
  const tool = isCapability(run.capability) ? t(CAP_META[run.capability].title) : run.capability
  return [runInput(run), tool, run.capability, run.status, t(STATUS_LABEL[run.status]), lang, run.error ?? '', run.id, JSON.stringify(run.result ?? '')]
    .join(' ')
    .toLowerCase()
}

export default function ToolsHistory() {
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const [runs, setRuns] = useState<Run[]>([])
  const [loaded, setLoaded] = useState(false)
  usePageLoading(!loaded)

  const [query, setQuery] = useState('')
  const [tool, setTool] = useState('all')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [language, setLanguage] = useState('all')
  const [when, setWhen] = useState<When>('all')
  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7))
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [oldestFirst, setOldestFirst] = useState(false)
  const [shown, setShown] = useState(PAGE)

  const load = useCallback(async () => {
    const { data, error } = await supabase.from('capability_runs').select(RUN_COLUMNS).order('created_at', { ascending: false }).limit(LIMIT)
    setLoaded(true)
    if (toastLoadError(t, error, () => load())) return
    setRuns((data as Run[]) ?? [])
  }, [t])

  useEffect(() => {
    load()
  }, [load])

  const searchable = useMemo(() => new Map(runs.map((r) => [r.id, haystack(r, t)])), [runs, t])
  const years = useMemo(() => {
    const set = new Set(runs.map((r) => r.created_at.slice(0, 4)))
    set.add(String(new Date().getFullYear()))
    return [...set].sort().reverse()
  }, [runs])

  const filtered = useMemo(() => {
    const now = new Date()
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
    const inWindow = (iso: string) => {
      const at = new Date(iso)
      const ms = at.getTime()
      switch (when) {
        case 'today':
          return ms >= startOfToday
        case '7d':
          return ms >= now.getTime() - 7 * 86400000
        case '30d':
          return ms >= now.getTime() - 30 * 86400000
        case 'month':
          return `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, '0')}` === month
        case 'year':
          return String(at.getFullYear()) === year
        case 'custom': {
          // Whole days, in the viewer's time zone.
          const afterFrom = !from || ms >= new Date(`${from}T00:00:00`).getTime()
          const beforeTo = !to || ms <= new Date(`${to}T23:59:59.999`).getTime()
          return afterFrom && beforeTo
        }
        default:
          return true
      }
    }
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    const list = runs.filter((r) => {
      if (tool !== 'all' && r.capability !== tool) return false
      if (status === 'completed' && r.status !== 'completed') return false
      if (status === 'failed' && r.status !== 'failed') return false
      if (status === 'active' && r.status !== 'pending' && r.status !== 'running') return false
      if (language !== 'all' && (r.params.target_language ?? 'en') !== language) return false
      if (!inWindow(r.created_at)) return false
      const text = searchable.get(r.id) ?? ''
      return words.every((w) => text.includes(w))
    })
    return oldestFirst ? [...list].reverse() : list
  }, [runs, searchable, query, tool, status, language, when, month, year, from, to, oldestFirst])

  // New filters start from the top of the list.
  useEffect(() => setShown(PAGE), [query, tool, status, language, when, month, year, from, to, oldestFirst])

  const filtersOn = query || tool !== 'all' || status !== 'all' || language !== 'all' || when !== 'all'
  function clearFilters() {
    setQuery('')
    setTool('all')
    setStatus('all')
    setLanguage('all')
    setWhen('all')
    setFrom('')
    setTo('')
  }

  const monthLabel = new Intl.DateTimeFormat(i18n.language, { month: 'long', year: 'numeric' })
  const stamp = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  const visible = filtered.slice(0, shown)
  const groups: { label: string; items: Run[] }[] = []
  for (const r of visible) {
    const label = monthLabel.format(new Date(r.created_at))
    if (groups[groups.length - 1]?.label !== label) groups.push({ label, items: [] })
    groups[groups.length - 1].items.push(r)
  }

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <Link to="/tools" className={`${local.back} link-wipe`}>
            ← {t('hist.back')}
          </Link>
          <h1 className={styles.title}>{t('hist.title')}</h1>
          <p className={styles.subtitle}>{t('hist.subtitle')}</p>
        </div>
      </header>

      <section className={`${styles.panel} ${local.filters} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties} aria-label={t('hist.filters')}>
        <label className={local.search}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <circle cx="11" cy="11" r="7" stroke="currentColor" strokeWidth="2" />
            <path d="M20 20l-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('hist.searchPh')} aria-label={t('hist.search')} />
        </label>

        <div className={local.row}>
          <label className={local.field}>
            <span>{t('hist.tool')}</span>
            <Select
              aria-label={t('hist.tool')}
              value={tool}
              onChange={setTool}
              options={[{ value: 'all', label: t('hist.anyTool') }, ...CAPABILITIES.map((c) => ({ value: c, label: t(CAP_META[c].title) }))]}
            />
          </label>
          <label className={local.field}>
            <span>{t('hist.status')}</span>
            <Select
              aria-label={t('hist.status')}
              value={status}
              onChange={(v) => setStatus(v as StatusFilter)}
              options={[
                { value: 'all', label: t('hist.anyStatus') },
                { value: 'completed', label: t('tl.stDone') },
                { value: 'failed', label: t('tl.stFailed') },
                { value: 'active', label: t('hist.inProgress') },
              ]}
            />
          </label>
          <label className={local.field}>
            <span>{t('hist.language')}</span>
            <Select
              aria-label={t('hist.language')}
              value={language}
              onChange={setLanguage}
              options={[{ value: 'all', label: t('hist.anyLanguage') }, ...CAMPAIGN_LANGUAGES.map((l) => ({ value: l.code, label: l.label }))]}
            />
          </label>
          <label className={local.field}>
            <span>{t('hist.when')}</span>
            <Select
              aria-label={t('hist.when')}
              value={when}
              onChange={(v) => setWhen(v as When)}
              options={(['all', 'today', '7d', '30d', 'month', 'year', 'custom'] as const).map((w) => ({ value: w, label: t(`hist.when_${w}`) }))}
            />
          </label>
          {when === 'month' && (
            <label className={local.field}>
              <span>{t('hist.month')}</span>
              <input className={styles.input} type="month" value={month} onChange={(e) => setMonth(e.target.value)} />
            </label>
          )}
          {when === 'year' && (
            <label className={local.field}>
              <span>{t('hist.year')}</span>
              <Select aria-label={t('hist.year')} value={year} onChange={setYear} options={years.map((y) => ({ value: y, label: y }))} />
            </label>
          )}
          {when === 'custom' && (
            <>
              <label className={local.field}>
                <span>{t('hist.from')}</span>
                <input className={styles.input} type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
              </label>
              <label className={local.field}>
                <span>{t('hist.to')}</span>
                <input className={styles.input} type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
              </label>
            </>
          )}
          <label className={local.field}>
            <span>{t('hist.sort')}</span>
            <Select
              aria-label={t('hist.sort')}
              value={oldestFirst ? 'old' : 'new'}
              onChange={(v) => setOldestFirst(v === 'old')}
              options={[
                { value: 'new', label: t('hist.newest') },
                { value: 'old', label: t('hist.oldest') },
              ]}
            />
          </label>
        </div>

        <div className={local.summaryRow}>
          <span className={styles.muted} aria-live="polite">
            {t('hist.count', { count: filtered.length })}
          </span>
          {filtersOn && (
            <button type="button" className={`${local.clear} link-wipe`} onClick={clearFilters}>
              {t('hist.clear')}
            </button>
          )}
        </div>
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
        {loaded && runs.length === 0 ? (
          <div className={local.empty}>
            <p>{t('hist.none')}</p>
            <Link to="/tools" className={`${styles.btn} ${styles.primary}`}>
              {t('hist.noneCta')}
            </Link>
          </div>
        ) : loaded && filtered.length === 0 ? (
          <div className={local.empty}>
            <p>{t('hist.noMatch')}</p>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={clearFilters}>
              {t('hist.clear')}
            </button>
          </div>
        ) : (
          groups.map((g) => (
            <div key={g.label} className={local.group}>
              <h2 className={local.groupTitle}>{g.label}</h2>
              <ul className={local.list}>
                {g.items.map((r) => {
                  const cap = isCapability(r.capability) ? r.capability : null
                  const lang = CAMPAIGN_LANGUAGES.find((l) => l.code === r.params.target_language)?.label
                  return (
                    <li key={r.id}>
                      <button type="button" className={local.item} onClick={() => navigate(`/tools?run=${r.id}`)}>
                        <span className={local.icon} aria-hidden="true">
                          <svg viewBox="0 0 24 24" fill="none">
                            {cap ? CAP_META[cap].icon : null}
                          </svg>
                        </span>
                        <span className={local.body}>
                          <span className={local.head}>
                            <strong>{cap ? t(CAP_META[cap].title) : r.capability}</strong>
                            <span className={`${local.status} ${local[`s_${r.status}`]}`}>{t(STATUS_LABEL[r.status])}</span>
                          </span>
                          <span className={local.input}>{runInput(r) || '—'}</span>
                          <span className={local.meta}>
                            {summary(r, t)}
                            {lang ? ` · ${lang}` : ''}
                          </span>
                        </span>
                        <time className={local.time} dateTime={r.created_at}>
                          {stamp.format(new Date(r.created_at))}
                        </time>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ))
        )}
        {filtered.length > shown && (
          <button type="button" className={`${styles.btn} ${styles.ghost} ${local.more}`} onClick={() => setShown((n) => n + PAGE)}>
            {t('hist.showMore', { count: Math.min(PAGE, filtered.length - shown) })}
          </button>
        )}
        {runs.length >= LIMIT && <p className={`${styles.muted} ${local.capped}`}>{t('hist.capped', { count: LIMIT })}</p>}
      </section>
    </div>
  )
}
