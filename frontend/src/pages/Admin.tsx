import { useCallback, useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate } from 'react-router-dom'

import Select from '../components/Select'
import { LoadingMarker } from '../components/PageLoader'
import { toast } from '../lib/toast'
import { toastFailure, toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './Admin.module.css'

interface OrgRow {
  id: string
  name: string
  plan: string
  personal: boolean
  members: number
  campaigns: number
  tokens_24h: number
  owner_email: string | null
  created_at: string
}

interface DeadRow {
  id: string
  campaign_id: string
  channel: string
  round_number: number
  attempts: number
  last_error: string | null
}

interface Flag {
  key: string
  description: string
  enabled: boolean
  rollout_percent: number
}

const PLANS = ['free', 'pro', 'enterprise'].map((p) => ({ value: p, label: p }))

/** Platform operators only (the database enforces it; this page just hides itself). */
export default function Admin() {
  const { t } = useTranslation()
  const [allowed, setAllowed] = useState<boolean | null>(null)
  const [overview, setOverview] = useState<Record<string, number>>({})
  const [orgs, setOrgs] = useState<OrgRow[]>([])
  const [dead, setDead] = useState<DeadRow[]>([])
  const [flags, setFlags] = useState<Flag[]>([])
  const [search, setSearch] = useState('')
  const [audit, setAudit] = useState<string | null>(null)
  const [newFlag, setNewFlag] = useState('')

  const load = useCallback(async () => {
    const [{ data: o, error }, { data: list }, { data: d }, { data: f }] = await Promise.all([
      supabase.rpc('admin_overview'),
      supabase.rpc('admin_orgs', { p_search: search }),
      supabase.rpc('admin_dead_deliveries'),
      supabase.rpc('admin_flags'),
    ])
    if (toastLoadError(t, error, () => load())) return
    setOverview((o as Record<string, number> | null) ?? {})
    setOrgs((list as OrgRow[] | null) ?? [])
    setDead((d as DeadRow[] | null) ?? [])
    setFlags((f as Flag[] | null) ?? [])
  }, [search, t])

  useEffect(() => {
    supabase.rpc('is_platform_admin').then(({ data }) => setAllowed(Boolean(data)))
  }, [])
  useEffect(() => {
    if (allowed) load()
  }, [allowed, load])

  // An operator action: confirm it, or show why it failed; then refresh.
  async function act(call: PromiseLike<{ error: { message: string } | null }>, done: string) {
    const { error } = await call
    if (!toastFailure(t, error)) toast.success(done)
    load()
  }

  if (allowed === false) return <Navigate to="/dashboard" replace />
  if (allowed === null) return <LoadingMarker />

  async function addFlag(e: FormEvent) {
    e.preventDefault()
    if (!/^[a-z][a-z0-9_]{1,63}$/.test(newFlag)) return
    await act(supabase.rpc('admin_set_flag', { p_key: newFlag, p_enabled: false, p_rollout: 100 }), t('toast.flagAdded', { key: newFlag }))
    setNewFlag('')
  }

  const tiles = ['users', 'organizations', 'active_campaigns', 'campaigns_24h', 'llm_tokens_24h', 'llm_failures_24h', 'dead_deliveries', 'failed_webhooks', 'paid_orgs']
  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('admin.eyebrow')}</span>
          <h1 className={styles.title}>{t('admin.title')}</h1>
          <p className={styles.subtitle}>{t('admin.subtitle')}</p>
        </div>
      </header>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
        <div className={local.tiles}>
          {tiles.map((k) => (
            <div key={k} className={['dead_deliveries', 'failed_webhooks', 'llm_failures_24h'].includes(k) && overview[k] ? local.alert : ''}>
              <span>{t(`admin.${k}`)}</span>
              <strong>{(overview[k] ?? 0).toLocaleString()}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('admin.orgs')}</h2>
          <input className={`${styles.input} ${local.search}`} placeholder={t('admin.search')} value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <div className={local.tableWrap}>
          <table className={local.table}>
            <thead>
              <tr>
                <th>{t('admin.org')}</th><th>{t('admin.owner')}</th><th>{t('admin.members')}</th>
                <th>{t('admin.campaigns')}</th><th>{t('admin.tokens')}</th><th>{t('admin.plan')}</th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((o) => (
                <tr key={o.id}>
                  <td>{o.personal ? <span className={styles.muted}>{t('org.personal')}</span> : o.name}</td>
                  <td>{o.owner_email ?? '—'}</td>
                  <td>{o.members}</td>
                  <td>{o.campaigns}</td>
                  <td>{Number(o.tokens_24h).toLocaleString()}</td>
                  <td className={local.planCell}>
                    <Select
                      aria-label={t('admin.plan')}
                      value={o.plan}
                      options={PLANS}
                      onChange={(plan) => act(supabase.rpc('admin_set_plan', { p_org: o.id, p_plan: plan }), t('toast.planSet', { name: o.name, plan }))}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
        <div className={styles.panelHead}><h2>{t('admin.dead', { count: dead.length })}</h2></div>
        {dead.length === 0 ? <p className={styles.muted}>{t('admin.noDead')}</p> : (
          <ul className={local.list}>
            {dead.map((d) => (
              <li key={d.id}>
                <code>{d.channel}</code> · {t('admin.round', { n: d.round_number })} · <span className={styles.muted}>{d.campaign_id.slice(0, 8)}</span>
                <span className={local.err}>{d.last_error}</span>
                <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => act(supabase.rpc('admin_retry_delivery', { p_delivery: d.id }), t('toast.retryQueued'))}>
                  {t('admin.retry')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
        <div className={styles.panelHead}><h2>{t('admin.flags')}</h2></div>
        <ul className={local.list}>
          {flags.map((f) => (
            <li key={f.key}>
              <code>{f.key}</code>
              <span className={styles.muted}>{f.description}</span>
              <label className={local.toggle}>
                <input type="checkbox" checked={f.enabled} onChange={(e) => act(supabase.rpc('admin_set_flag', { p_key: f.key, p_enabled: e.target.checked, p_rollout: f.rollout_percent }), t('toast.flagSaved', { key: f.key }))} />
                {t('admin.on')}
              </label>
              <input
                className={`${styles.input} ${local.pct}`}
                type="number" min={0} max={100} defaultValue={f.rollout_percent} aria-label={t('admin.rollout')}
                onBlur={(e) => {
                  if (Number(e.target.value) === f.rollout_percent) return
                  act(supabase.rpc('admin_set_flag', { p_key: f.key, p_enabled: f.enabled, p_rollout: Number(e.target.value) }), t('toast.flagSaved', { key: f.key }))
                }}
              />%
            </li>
          ))}
        </ul>
        <form onSubmit={addFlag} className={local.inline}>
          <input className={styles.input} value={newFlag} onChange={(e) => setNewFlag(e.target.value.toLowerCase())} placeholder="new_flag_key" pattern="[a-z][a-z0-9_]{1,63}" />
          <button className={`${styles.btn} ${styles.ghost}`}>{t('admin.addFlag')}</button>
        </form>
      </section>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
        <div className={styles.panelHead}><h2>{t('admin.auditTitle')}</h2></div>
        <div className={local.inline}>
          <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={async () => {
            const { data, error } = await supabase.rpc('admin_verify_audit')
            if (toastFailure(t, error) || !data) return
            const r = data as { intact: boolean; first_broken_id: number | null; rows: number }
            setAudit(r.intact ? t('admin.auditOk', { rows: r.rows }) : t('admin.auditBroken', { id: r.first_broken_id }))
          }}>{t('admin.verify')}</button>
          {audit && <span className={styles.muted}>{audit}</span>}
        </div>
      </section>
    </div>
  )
}
