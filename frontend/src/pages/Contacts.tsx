import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import ContactDetail from '../components/ContactDetail'
import Segments from '../components/Segments'
import Select from '../components/Select'
import { CONTACT_FIELDS, guessMapping, parseCsv, rowToContact, type ContactField } from '../lib/csv'
import { usePageLoading } from '../lib/loading'
import { toastFailure, toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import type { ConsentSource, Contact, ContactCounts, ContactStatus, ImportResult } from '../lib/types'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './Contacts.module.css'

const PAGE = 50
const SUNSET_MS = 730 * 86_400_000 // 24 months without a click or purchase
const CHUNK = 500 // rows per upsert_contacts call (the function takes up to 1000)
const STATUSES: ContactStatus[] = ['subscribed', 'pending', 'unsubscribed', 'bounced', 'complained']
const SOURCES: ConsentSource[] = ['checkout', 'signup_form', 'in_store', 'event', 'other']

function Counts({ counts }: { counts: ContactCounts | null }) {
  const { t, i18n } = useTranslation()
  const n = (x: number) => x.toLocaleString(i18n.language)
  const c = counts ?? { total: 0, subscribed: 0, pending: 0, unsubscribed: 0, bounced: 0, complained: 0, cap: null }
  return (
    <section className={`${styles.panel} ${local.counts}`} data-testid="contact-counts">
      <dl className={local.tiles}>
        <div><dt>{t('ct.status.subscribed')}</dt><dd>{n(c.subscribed)}</dd></div>
        <div><dt>{t('ct.status.pending')}</dt><dd>{n(c.pending)}</dd></div>
        <div><dt>{t('ct.status.unsubscribed')}</dt><dd>{n(c.unsubscribed)}</dd></div>
        <div><dt>{t('ct.bouncedOrComplained')}</dt><dd>{n(c.bounced + c.complained)}</dd></div>
      </dl>
      <p className={local.cap}>
        {c.cap === null ? t('ct.totalNoCap', { n: n(c.total) }) : t('ct.totalOfCap', { n: n(c.total), cap: n(c.cap) })}
        {(c.inactive ?? 0) > 0 && ` · ${t('ct.inactiveCount', { count: c.inactive })}`}
      </p>
    </section>
  )
}

function ImportWizard({ orgId, onDone, onClose }: { orgId: string; onDone: () => void; onClose: () => void }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<string[][] | null>(null)
  const [fileName, setFileName] = useState('')
  const [map, setMap] = useState<Partial<Record<ContactField, number>>>({})
  const [source, setSource] = useState<ConsentSource | ''>('')
  const [note, setNote] = useState('')
  const [attested, setAttested] = useState(false)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<ImportResult | null>(null)
  const headers = rows?.[0] ?? []
  const body = useMemo(() => rows?.slice(1) ?? [], [rows])
  const contacts = useMemo(() => body.map((r) => rowToContact(r, map)), [body, map])

  async function pick(file: File | undefined) {
    if (!file) return
    setFileName(file.name)
    setResult(null)
    const parsed = parseCsv(await file.text())
    setRows(parsed)
    setMap(guessMapping(parsed[0] ?? []))
  }

  async function run() {
    if (!source) return
    setBusy(true)
    const total: ImportResult = { added: 0, updated: 0, skipped: [] }
    for (let i = 0; i < contacts.length; i += CHUNK) {
      const { data, error } = await supabase.rpc('upsert_contacts', {
        p_org: orgId, p_rows: contacts.slice(i, i + CHUNK), p_source: source, p_note: note.trim() || null,
        p_consent_text: t('ct.attest'),
      })
      if (toastFailure(t, error)) break
      const r = data as ImportResult
      total.added += r.added
      total.updated += r.updated
      total.skipped.push(...r.skipped)
    }
    setBusy(false)
    setResult(total)
    onDone()
  }

  const columnOptions = [{ value: -1, label: t('ct.notInFile') }, ...headers.map((h, i) => ({ value: i, label: h || t('ct.column', { n: i + 1 }) }))]
  const ready = rows && map.email !== undefined && source && attested && contacts.length > 0

  return (
    <section className={`${styles.panel} ${local.wizard}`} data-testid="import-wizard">
      <div className={styles.panelHead}>
        <div><h2>{t('ct.importTitle')}</h2><p className={styles.panelSub}>{t('ct.importSub')}</p></div>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={onClose}>{t('ct.close')}</button>
      </div>

      <label className={local.file}>
        <span>{t('ct.file')}</span>
        <input type="file" accept=".csv,text/csv" onChange={(e) => pick(e.target.files?.[0])} />
      </label>

      {rows && (
        <>
          <p className={local.meta}>{fileName} · {t('ct.rows', { count: body.length })}</p>
          <fieldset className={local.mapping}>
            <legend>{t('ct.mapTitle')}</legend>
            {CONTACT_FIELDS.map((f) => (
              <label key={f} className={styles.field}>
                <span>{t(`ct.field.${f}`)}{f === 'email' ? ' *' : ''}</span>
                <Select aria-label={t(`ct.field.${f}`)} value={map[f] ?? -1} options={columnOptions}
                  onChange={(v) => setMap((m) => ({ ...m, [f]: v === -1 ? undefined : v }))} />
              </label>
            ))}
          </fieldset>
          {contacts.length > 0 && map.email !== undefined && (
            <div className={local.preview}>
              <p className={local.meta}>{t('ct.preview')}</p>
              <ul>{contacts.slice(0, 3).map((c, i) => (
                <li key={i}>{String(c.email)}{c.first_name ? ` · ${String(c.first_name)}` : ''}
                  {(c.tags as string[]).map((tag) => <span key={tag} className={local.tag}>{tag}</span>)}</li>
              ))}</ul>
            </div>
          )}

          <div className={local.consent}>
            <label className={styles.field}><span>{t('ct.sourceLabel')}</span>
              <Select aria-label={t('ct.sourceLabel')} value={source}
                options={[{ value: '', label: t('ct.choose'), disabled: true }, ...SOURCES.map((s) => ({ value: s, label: t(`ct.sourceOption.${s}`) }))]}
                onChange={(v) => setSource(v as ConsentSource)} /></label>
            <label className={styles.field}><span>{t('ct.noteLabel')}</span>
              <input className={styles.input} value={note} maxLength={200} onChange={(e) => setNote(e.target.value)} placeholder={t('ct.notePlaceholder')} /></label>
          </div>
          <label className={local.attest}>
            <input type="checkbox" checked={attested} onChange={(e) => setAttested(e.target.checked)} />
            <span>{t('ct.attest')}</span>
          </label>
          <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={!ready || busy} onClick={run}>
            {t('ct.importN', { count: contacts.length })}
          </button>
        </>
      )}

      {result && (
        <div className={local.result} data-testid="import-result" role="status">
          <p>{t('ct.resultLine', { added: result.added, updated: result.updated, skipped: result.skipped.length })}</p>
          {result.skipped.length > 0 && (
            <details>
              <summary>{t('ct.skippedN', { count: result.skipped.length })}</summary>
              <ul>{result.skipped.map((s, i) => <li key={i}><span>{s.email}</span> <span className={local.reason}>{t(`ct.reason.${s.reason}`)}</span></li>)}</ul>
            </details>
          )}
        </div>
      )}
    </section>
  )
}

/** Contacts: the brand's own customers and subscribers, with how each agreed to hear from it. */
export default function Contacts() {
  const { t, i18n } = useTranslation()
  const { active, can } = useOrg()
  const canSee = !!active && (can('create', active.id) || can('manage', active.id))
  const canManage = !!active && can('manage', active.id)
  const [counts, setCounts] = useState<ContactCounts | null>(null)
  const [tags, setTags] = useState<{ tag: string; people: number }[]>([])
  const [rows, setRows] = useState<Contact[]>([])
  const [more, setMore] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<ContactStatus | 'all'>('all')
  const [tag, setTag] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  usePageLoading(!loaded)

  useEffect(() => {
    const id = window.setTimeout(() => setSearch(query.trim().replace(/[,()*]/g, ' ').trim()), 250)
    return () => window.clearTimeout(id)
  }, [query])

  const loadCounts = useCallback(async () => {
    if (!active) return
    const [c, tg] = await Promise.all([supabase.rpc('contact_counts', { p_org: active.id }), supabase.rpc('contact_tags', { p_org: active.id })])
    setLoaded(true)
    if (toastLoadError(t, c.error || tg.error, () => loadCounts())) return
    setCounts(c.data as ContactCounts)
    setTags((tg.data as { tag: string; people: number }[]) ?? [])
  }, [active, t])

  const loadRows = useCallback(async (from = 0) => {
    if (!active || !canSee) return
    let q = supabase.from('contacts').select('id,email,first_name,name,tags,status,consent_source,created_at,consent_at,last_engaged_at')
      .eq('org_id', active.id).order('created_at', { ascending: false }).range(from, from + PAGE - 1)
    if (search) q = q.or(`email.ilike.*${search}*,first_name.ilike.*${search}*,name.ilike.*${search}*`)
    if (status !== 'all') q = q.eq('status', status)
    if (tag) q = q.contains('tags', [tag])
    const { data, error } = await q
    if (toastLoadError(t, error, () => loadRows(from))) return
    const page = (data as Contact[]) ?? []
    setRows((prev) => (from ? [...prev, ...page] : page))
    setMore(page.length === PAGE)
  }, [active, canSee, search, status, tag, t])

  useEffect(() => { loadCounts() }, [loadCounts])
  useEffect(() => { loadRows(0) }, [loadRows])

  async function exportAll() {
    if (!active) return
    const { data, error } = await supabase.rpc('export_contacts', { p_org: active.id })
    if (toastFailure(t, error)) return
    const cols = ['email', 'first_name', 'name', 'language', 'tags', 'status', 'consent_source', 'consent_note', 'consent_text',
      'consent_at', 'confirmed_at', 'last_engaged_at', 'attributes', 'history']
    // Tags as "a;b", nested values (attributes, history) as JSON; quoted when needed.
    const cell = (v: unknown) => {
      const text = v == null ? '' : col(v)
      return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
    }
    const col = (v: unknown) => (Array.isArray(v) && v.every((x) => typeof x === 'string') ? v.join(';') : typeof v === 'object' ? JSON.stringify(v) : String(v))
    const csv = [cols.join(','), ...(data as Record<string, unknown>[]).map((r) => cols.map((c) => cell(r[c])).join(','))].join('\n')
    const a = document.createElement('a')
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }))
    a.download = `contacts-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const day = (iso: string) => new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' })

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('ct.eyebrow')}</span>
          <h1 className={styles.title}>{t('ct.title')}</h1>
          <p className={styles.subtitle}>{t('ct.subtitle')}</p>
        </div>
        <div className={local.headActions}>
          {canManage && <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={exportAll}>{t('ct.export')}</button>}
          {canSee && !importing && (
            <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={() => setImporting(true)}>{t('ct.import')}</button>
          )}
        </div>
      </header>

      <Counts counts={counts} />

      {importing && active && (
        <ImportWizard orgId={active.id} onClose={() => setImporting(false)} onDone={() => { loadCounts(); loadRows(0) }} />
      )}

      {canSee ? (
        <section className={styles.panel}>
          <div className={local.toolbar}>
            <input type="search" className={`${styles.input} ${local.search}`} aria-label={t('ct.search')} placeholder={t('ct.searchPlaceholder')}
              value={query} onChange={(e) => setQuery(e.target.value)} />
            <nav className={local.filters} aria-label={t('ct.statusFilter')}>
              {(['all', ...STATUSES] as const).map((s) => (
                <button key={s} type="button" className={`${local.filter} ${status === s ? local.filterOn : ''}`} aria-pressed={status === s} onClick={() => setStatus(s)}>
                  {s === 'all' ? t('ct.all') : t(`ct.status.${s}`)}
                </button>
              ))}
            </nav>
            {tags.length > 0 && (
              <nav className={local.filters} aria-label={t('ct.tagFilter')}>
                {tags.slice(0, 20).map(({ tag: name, people }) => (
                  <button key={name} type="button" className={`${local.filter} ${tag === name ? local.filterOn : ''}`} aria-pressed={tag === name}
                    onClick={() => setTag(tag === name ? null : name)}>{name} · {people}</button>
                ))}
              </nav>
            )}
          </div>
          {rows.length ? (
            <ul className={local.list} data-testid="contact-list">
              {rows.map((c) => (
                <li key={c.id} className={local.row} data-testid={`contact-${c.id}`}>
                  <div className={local.who}>
                    <span className={local.email}>{c.email}</span>
                    {(c.first_name || c.name) && <span className={local.meta}>{c.name || c.first_name}</span>}
                  </div>
                  <div className={local.tags}>{c.tags.map((x) => <span key={x} className={local.tag}>{x}</span>)}</div>
                  <div className={local.facts}>
                    <span className={`${local.status} ${local[c.status] ?? ''}`}>
                      {c.status === 'subscribed' && Date.now() - new Date(c.last_engaged_at ?? c.consent_at).getTime() > SUNSET_MS
                        ? t('ct.inactive') : t(`ct.status.${c.status}`)}
                    </span>
                    <span className={local.meta}>{t(`ct.source.${c.consent_source}`)} · {day(c.created_at)}</span>
                    <button type="button" className={local.more2} aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>
                      {t('ct.details')}
                    </button>
                  </div>
                  {open === c.id && (
                    <ContactDetail id={c.id} canErase={canManage} onErased={() => { setOpen(null); loadCounts(); loadRows(0) }} />
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <div data-testid="contact-list" className={styles.empty}>
              <h3>{loaded && !search && status === 'all' && !tag ? t('ct.emptyTitle') : t('ct.noMatch')}</h3>
              {loaded && !search && status === 'all' && !tag && <p>{t('ct.emptyBody')}</p>}
            </div>
          )}
          {more && <button type="button" className={`${styles.btn} ${styles.ghost} ${local.more}`} onClick={() => loadRows(rows.length)}>{t('ct.loadMore')}</button>}
        </section>
      ) : (
        <p className={local.meta}>{t('ct.viewerNote')}</p>
      )}

      {active && <Segments orgId={active.id} canEdit={canSee} tags={tags} />}
    </div>
  )
}
