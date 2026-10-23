import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'
import { toast } from '../lib/toast'
import { copyWithToast, toastFailure, toastLoadError } from '../lib/notify'

interface ApiKey {
  id: string
  name: string
  prefix: string
  scopes: string[]
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
}

interface Webhook {
  id: string
  url: string
  secret: string
  events: string[]
  active: boolean
}

interface Delivery {
  id: number
  event: string
  status: string
  attempts: number
  response_status: number | null
  created_at: string
}

const EVENT_PRESETS = ['*', 'campaign.*', 'gate.*', 'delivery.*', 'membership.*']

/** Organisation API keys and webhooks (owners/admins). See docs/openapi.yaml. */
export default function ApiSettings() {
  const { t, i18n } = useTranslation()
  const { active } = useOrg()
  const [keys, setKeys] = useState<ApiKey[]>([])
  const [hooks, setHooks] = useState<Webhook[]>([])
  const [deliveries, setDeliveries] = useState<Delivery[]>([])
  const [keyName, setKeyName] = useState('')
  const [canWrite, setCanWrite] = useState(false)
  const [newKey, setNewKey] = useState<string | null>(null)
  const [hookUrl, setHookUrl] = useState('')
  const [events, setEvents] = useState<string[]>(['*'])

  const orgId = active?.id
  const load = useCallback(async () => {
    if (!orgId) return
    const [{ data: k, error: keysError }, { data: w }] = await Promise.all([
      supabase.from('api_keys').select('id,name,prefix,scopes,created_at,last_used_at,revoked_at').eq('org_id', orgId).order('created_at', { ascending: false }),
      supabase.from('webhooks').select('id,url,secret,events,active').eq('org_id', orgId).order('created_at'),
    ])
    if (toastLoadError(t, keysError, () => load())) return
    setKeys((k as ApiKey[] | null) ?? [])
    const hookList = (w as Webhook[] | null) ?? []
    setHooks(hookList)
    if (hookList.length) {
      const { data: d } = await supabase
        .from('webhook_deliveries')
        .select('id,event,status,attempts,response_status,created_at')
        .in('webhook_id', hookList.map((h) => h.id))
        .order('id', { ascending: false })
        .limit(10)
      setDeliveries((d as Delivery[] | null) ?? [])
    }
  }, [orgId, t])

  useEffect(() => {
    load()
  }, [load])

  async function createKey(e: FormEvent) {
    e.preventDefault()
    if (!orgId || !keyName.trim()) return
    const { data, error: err } = await supabase.rpc('create_api_key', { p_org: orgId, p_name: keyName.trim(), p_scopes: canWrite ? ['read', 'write'] : ['read'] })
    if (toastFailure(t, err)) return
    setNewKey(data as string)
    setKeyName('')
    load()
  }

  async function addHook(e: FormEvent) {
    e.preventDefault()
    if (!orgId) return
    const { error: err } = await supabase.from('webhooks').insert({ org_id: orgId, url: hookUrl.trim(), events })
    if (toastFailure(t, err)) return
    toast.success(t('toast.webhookAdded'))
    setHookUrl('')
    load()
  }

  const when = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  return (
    <div className={local.team}>
      <p className={styles.muted}>
        {t('api.intro')} <code>{`${import.meta.env.VITE_SUPABASE_URL ?? ''}/functions/v1/api/v1/campaigns`}</code>
      </p>

      <h3 className={local.subhead}>{t('api.keys')}</h3>
      {keys.length > 0 && (
        <ul className={local.members}>
          {keys.map((k) => (
            <li key={k.id} className={local.member}>
              <div className={local.who}>
                <strong>{k.name} <code>{k.prefix}…</code></strong>
                <span className={styles.muted}>
                  {k.revoked_at ? t('api.revoked') : k.last_used_at ? t('api.lastUsed', { when: when.format(new Date(k.last_used_at)) }) : t('api.neverUsed')}
                </span>
              </div>
              <span className={styles.chip}>{k.scopes.join(' + ')}</span>
              {!k.revoked_at && (
                <button type="button" className={`${styles.btn} ${styles.danger} ${local.small}`} onClick={async () => {
                  const { error: err } = await supabase.rpc('revoke_api_key', { p_key: k.id })
                  if (!toastFailure(t, err)) toast.success(t('toast.keyRevoked', { name: k.name }))
                  load()
                }}>
                  {t('api.revoke')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <form className={local.inviteForm} onSubmit={createKey}>
        <label className={styles.field}>
          <span>{t('api.keyName')}</span>
          <input className={styles.input} maxLength={60} value={keyName} onChange={(e) => setKeyName(e.target.value)} placeholder="Zapier, CI…" />
        </label>
        <label className={local.check}>
          <input type="checkbox" checked={canWrite} onChange={(e) => setCanWrite(e.target.checked)} />
          <span>{t('api.allowWrite')}</span>
        </label>
        <button className={`${styles.btn} ${styles.primary}`} disabled={!keyName.trim()}>{t('api.create')}</button>
      </form>
      {newKey && (
        <div className={local.link}>
          <p className={styles.muted}>{t('api.copyOnce')}</p>
          <div className={local.inline}>
            <input className={styles.input} readOnly value={newKey} onFocus={(e) => e.target.select()} aria-label={t('api.keys')} />
            <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => copyWithToast(t, newKey)}>{t('org.copy')}</button>
          </div>
        </div>
      )}

      <h3 className={local.subhead}>{t('api.webhooks')}</h3>
      {hooks.length > 0 && (
        <ul className={local.members}>
          {hooks.map((h) => (
            <li key={h.id} className={local.member}>
              <div className={local.who}>
                <strong>{h.url}</strong>
                <span className={styles.muted}>{t('api.secret')}: <code>{h.secret.slice(0, 6)}…</code> · {h.events.join(', ')}</span>
              </div>
              <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={() => copyWithToast(t, h.secret)}>{t('api.copySecret')}</button>
              <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={async () => {
                const { error: err } = await supabase.rpc('ping_webhook', { p_webhook: h.id })
                if (!toastFailure(t, err)) toast.success(t('toast.webhookPinged'))
                setTimeout(load, 1500)
              }}>{t('api.test')}</button>
              <button type="button" className={`${styles.btn} ${styles.danger} ${local.small}`} onClick={async () => {
                const { error: err } = await supabase.from('webhooks').delete().eq('id', h.id)
                if (!toastFailure(t, err)) toast.success(t('toast.webhookRemoved'))
                load()
              }}>{t('org.remove')}</button>
            </li>
          ))}
        </ul>
      )}
      <form className={local.team} onSubmit={addHook}>
        <label className={styles.field}>
          <span>{t('api.endpoint')}</span>
          <input className={styles.input} type="url" required pattern="https://.*" value={hookUrl} onChange={(e) => setHookUrl(e.target.value)} placeholder="https://example.com/marketingos" />
        </label>
        <div className={local.inline} style={{ flexWrap: 'wrap' }}>
          {EVENT_PRESETS.map((ev) => (
            <label key={ev} className={local.check}>
              <input
                type="checkbox"
                checked={events.includes(ev)}
                onChange={(e) => setEvents((cur) => (e.target.checked ? [...cur.filter((x) => x !== '*' || ev === '*'), ev] : cur.filter((x) => x !== ev)))}
              />
              <span><code>{ev}</code></span>
            </label>
          ))}
        </div>
        <div>
          <button className={`${styles.btn} ${styles.primary}`} disabled={!hookUrl.trim() || !events.length}>{t('api.addHook')}</button>
        </div>
      </form>
      {deliveries.length > 0 && (
        <details>
          <summary className={styles.muted}>{t('api.recent')}</summary>
          <ul className={local.members} style={{ marginTop: 8 }}>
            {deliveries.map((d) => (
              <li key={d.id} className={local.member}>
                <div className={local.who}>
                  <strong><code>{d.event}</code></strong>
                  <span className={styles.muted}>{when.format(new Date(d.created_at))} · {t('api.attempts', { count: d.attempts })}</span>
                </div>
                <span className={styles.chip}>{d.status}{d.response_status ? ` · ${d.response_status}` : ''}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}
