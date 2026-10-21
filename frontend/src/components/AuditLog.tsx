import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './AuditLog.module.css'
import Select from './Select'

interface AuditRow {
  id: number
  created_at: string
  actor_id: string | null
  actor_type: 'user' | 'system'
  action: string
  target_type: string
  target_id: string | null
  details: unknown
  hash: string
}

const PAGE = 100
const EXPORT_LIMIT = 5000
const AREAS = ['campaign', 'gate', 'membership', 'invitation', 'organization', 'provider_key', 'delivery', 'feature_flag']

function download(name: string, body: string, type: string) {
  const url = URL.createObjectURL(new Blob([body], { type }))
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

const csvCell = (v: unknown) => {
  const s = v == null ? '' : typeof v === 'string' ? v : JSON.stringify(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/**
 * The organisation's audit trail (managers only; RLS enforces it). Rows are
 * written by database triggers and hash-chained, so this is a read-only view.
 */
export default function AuditLog() {
  const { t, i18n } = useTranslation()
  const { active } = useOrg()
  const [rows, setRows] = useState<AuditRow[]>([])
  const [people, setPeople] = useState<Record<string, string>>({})
  const [area, setArea] = useState('')
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState(false)

  const query = useCallback(
    (limit: number, before?: number) => {
      let q = supabase
        .from('audit_log')
        .select('id,created_at,actor_id,actor_type,action,target_type,target_id,details,hash')
        .eq('org_id', active?.id ?? '')
        .order('id', { ascending: false })
        .limit(limit)
      if (area) q = q.like('action', `${area}.%`)
      if (before) q = q.lt('id', before)
      return q
    },
    [active?.id, area],
  )

  const load = useCallback(async () => {
    if (!active) return
    const [{ data }, { data: members }] = await Promise.all([query(PAGE), supabase.rpc('org_members', { p_org: active.id })])
    setRows((data as AuditRow[] | null) ?? [])
    setMore((data?.length ?? 0) === PAGE)
    setPeople(Object.fromEntries(((members as { user_id: string; email: string }[] | null) ?? []).map((m) => [m.user_id, m.email])))
  }, [active, query])

  useEffect(() => {
    load()
  }, [load])

  async function loadMore() {
    const { data } = await query(PAGE, rows[rows.length - 1]?.id)
    setRows((r) => [...r, ...((data as AuditRow[] | null) ?? [])])
    setMore((data?.length ?? 0) === PAGE)
  }

  async function exportAs(format: 'csv' | 'json') {
    setBusy(true)
    const { data } = await query(EXPORT_LIMIT)
    const all = (data as AuditRow[] | null) ?? []
    const stamp = new Date().toISOString().slice(0, 10)
    if (format === 'json') {
      download(`audit-${stamp}.json`, JSON.stringify(all, null, 2), 'application/json')
    } else {
      const head = ['id', 'created_at', 'actor', 'actor_type', 'action', 'target_type', 'target_id', 'details', 'hash']
      const lines = all.map((r) =>
        [r.id, r.created_at, r.actor_id ? (people[r.actor_id] ?? r.actor_id) : 'system', r.actor_type, r.action, r.target_type, r.target_id, r.details, r.hash]
          .map(csvCell)
          .join(','),
      )
      download(`audit-${stamp}.csv`, [head.join(','), ...lines].join('\n'), 'text/csv')
    }
    setBusy(false)
  }

  const when = useMemo(
    () => new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' }),
    [i18n.language],
  )

  return (
    <div className={local.audit}>
      <div className={local.toolbar}>
        <Select
          aria-label={t('audit.filter')}
          value={area}
          onChange={setArea}
          options={[{ value: '', label: t('audit.all') }, ...AREAS.map((a) => ({ value: a, label: a.replace('_', ' ') }))]}
        />
        <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy} onClick={() => exportAs('csv')}>
          {t('audit.exportCsv')}
        </button>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy} onClick={() => exportAs('json')}>
          {t('audit.exportJson')}
        </button>
      </div>
      {rows.length === 0 ? (
        <p className={styles.muted}>{t('audit.empty')}</p>
      ) : (
        <ol className={local.list}>
          {rows.map((r) => (
            <li key={r.id} className={local.row}>
              <time dateTime={r.created_at}>{when.format(new Date(r.created_at))}</time>
              <code className={local.action}>{r.action}</code>
              <span className={local.actor}>{r.actor_id ? (people[r.actor_id] ?? r.actor_id.slice(0, 8)) : t('audit.system')}</span>
              {r.details != null && JSON.stringify(r.details) !== '{}' && (
                <span className={local.details}>{JSON.stringify(r.details)}</span>
              )}
            </li>
          ))}
        </ol>
      )}
      {more && (
        <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={loadMore}>
          {t('audit.more')}
        </button>
      )}
      <p className={local.note}>{t('audit.note')}</p>
    </div>
  )
}
