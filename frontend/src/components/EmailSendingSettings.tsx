import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import Select from './Select'
import { toastFailure } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import type { EmailStatus } from '../lib/types'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './EmailSendingSettings.module.css'

interface Domain { id: string; name: string; verified: boolean }
const HOURS = Array.from({ length: 25 }, (_, h) => h)
const hour = (h: number) => `${String(h).padStart(2, '0')}:00`

/** Why a setup call failed, in words (the function answers {error, code}). */
async function failure(error: unknown, response?: Response): Promise<{ code?: string; message: string }> {
  try {
    const body = await response?.clone().json()
    if (body?.error) return { code: body.code, message: body.error }
  } catch {
    /* not JSON */
  }
  return { message: error instanceof Error ? error.message : String(error) }
}

function Connect({ orgId, orgName, hasAddress, onDone }: { orgId: string; orgName: string; hasAddress: boolean; onDone: () => void }) {
  const { t } = useTranslation()
  const [key, setKey] = useState('')
  const [domains, setDomains] = useState<Domain[] | null>(null)
  const [mode, setMode] = useState<'live' | 'sandbox'>('live')
  const [domainId, setDomainId] = useState('')
  const [fromLocal, setFromLocal] = useState('hello')
  const [fromName, setFromName] = useState(orgName)
  const [replyTo, setReplyTo] = useState('')
  const [sandboxTo, setSandboxTo] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')
  const verified = (domains ?? []).filter((d) => d.verified)

  async function call(body: Record<string, unknown>) {
    setBusy(true)
    setProblem('')
    const { data, error, response } = await supabase.functions.invoke('email-setup', { body: { org_id: orgId, api_key: key.trim(), ...body } })
    setBusy(false)
    if (!error) return data
    const f = await failure(error, response)
    setProblem(f.code ? t(`em.err.${f.code}`, f.message) : f.message)
    return null
  }

  async function inspect() {
    const data = await call({ action: 'inspect' })
    if (!data) return
    const list = (data.domains as Domain[]) ?? []
    setDomains(list)
    const first = list.find((d) => d.verified)
    setMode(first ? 'live' : 'sandbox')
    setDomainId(first?.id ?? '')
  }

  async function connect() {
    const data = await call({
      action: 'connect', mode, domain_id: mode === 'live' ? domainId : undefined, from_local: fromLocal, from_name: fromName,
      reply_to: replyTo.trim() || undefined, sandbox_to: mode === 'sandbox' ? sandboxTo.trim() : undefined,
    })
    if (!data) return
    setKey('')
    toast.success(t(mode === 'live' ? 'em.connectedLive' : 'em.connectedSandbox'))
    onDone()
  }

  const domainName = verified.find((d) => d.id === domainId)?.name ?? ''
  const canConnect = hasAddress && fromName.trim() && (mode === 'live' ? domainId && fromLocal.trim() : /^[^@\s]+@[^@\s]+$/.test(sandboxTo.trim()))

  return (
    <div className={local.connect} data-testid="email-connect">
      <ol className={local.steps}>
        <li>{t('em.step1')}</li>
        <li>{t('em.step2')}</li>
        <li>{t('em.step3')}</li>
      </ol>
      <div className={local.keyRow}>
        <label className={styles.field}>
          <span>{t('em.keyLabel')}</span>
          <input className={styles.input} type="password" autoComplete="off" value={key} onChange={(e) => { setKey(e.target.value); setDomains(null) }}
            placeholder="re_..." />
        </label>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy || key.trim().length < 8} onClick={inspect}>{t('em.check')}</button>
      </div>
      <p className={styles.muted}>{t('em.keyWhy')}</p>

      {domains && (
        <>
          {verified.length > 0 ? (
            <div className={local.modes} role="radiogroup" aria-label={t('em.modeLabel')}>
              <label><input type="radio" name="mode" checked={mode === 'live'} onChange={() => setMode('live')} /> {t('em.modeLive')}</label>
              <label><input type="radio" name="mode" checked={mode === 'sandbox'} onChange={() => setMode('sandbox')} /> {t('em.modeSandbox')}</label>
            </div>
          ) : (
            <div className={local.note} role="note">
              <strong>{t('em.noDomainTitle')}</strong>
              <p>{t('em.noDomainBody')}</p>
              <a href="https://resend.com/domains" target="_blank" rel="noreferrer">{t('em.addDomain')}</a>
            </div>
          )}

          {mode === 'live' && verified.length > 0 && (
            <div className={local.grid}>
              <label className={styles.field}><span>{t('em.domain')}</span>
                <Select aria-label={t('em.domain')} value={domainId} onChange={setDomainId} options={verified.map((d) => ({ value: d.id, label: d.name }))} /></label>
              <label className={styles.field}><span>{t('em.fromAddress')}</span>
                <span className={local.address}>
                  <input className={styles.input} aria-label={t('em.fromAddress')} value={fromLocal} onChange={(e) => setFromLocal(e.target.value)} />
                  <span>@{domainName}</span>
                </span></label>
            </div>
          )}
          {mode === 'sandbox' && (
            <label className={styles.field}><span>{t('em.sandboxTo')}</span>
              <input className={styles.input} type="email" value={sandboxTo} onChange={(e) => setSandboxTo(e.target.value)} placeholder="you@example.com" /></label>
          )}
          {mode === 'sandbox' && <p className={styles.muted}>{t('em.sandboxWhy')}</p>}
          <div className={local.grid}>
            <label className={styles.field}><span>{t('em.fromName')}</span>
              <input className={styles.input} maxLength={80} value={fromName} onChange={(e) => setFromName(e.target.value)} /></label>
            <label className={styles.field}><span>{t('em.replyTo')}</span>
              <input className={styles.input} type="email" value={replyTo} onChange={(e) => setReplyTo(e.target.value)} placeholder="support@yourbrand.com" /></label>
          </div>
          {!hasAddress && <p className={local.warn} role="alert">{t('em.needAddress')} <a href="#brand">{t('em.toBrandKit')}</a></p>}
          <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy || !canConnect} onClick={connect}>
            {mode === 'live' ? t('em.connectLive') : t('em.connectSandbox')}
          </button>
        </>
      )}
      {problem && <p className={local.warn} role="alert">{problem}</p>}
    </div>
  )
}

function Preferences({ orgId, status, onDone }: { orgId: string; status: EmailStatus; onDone: () => void }) {
  const { t } = useTranslation()
  const [limit, setLimit] = useState(String(status.daily_limit ?? 100))
  const [start, setStart] = useState(status.send_window_start ?? 9)
  const [end, setEnd] = useState(status.send_window_end ?? 20)
  const [tz, setTz] = useState(status.timezone ?? 'UTC')
  const zones = useMemo(() => {
    try {
      return (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone')
    } catch {
      return ['UTC']
    }
  }, [])

  async function save() {
    const { error } = await supabase.rpc('update_email_preferences', { p_org: orgId, p_daily_limit: Number(limit), p_start: start, p_end: end, p_timezone: tz })
    if (toastFailure(t, error)) return
    toast.success(t('em.savedPrefs'))
    onDone()
  }

  return (
    <div className={local.prefs}>
      <label className={styles.field}><span>{t('em.dailyLimit')}</span>
        <input className={styles.input} type="number" min={1} max={100000} value={limit} onChange={(e) => setLimit(e.target.value)} /></label>
      <label className={styles.field}><span>{t('em.windowStart')}</span>
        <Select aria-label={t('em.windowStart')} value={start} onChange={setStart} options={HOURS.slice(0, 24).map((h) => ({ value: h, label: hour(h) }))} /></label>
      <label className={styles.field}><span>{t('em.windowEnd')}</span>
        <Select aria-label={t('em.windowEnd')} value={end} onChange={setEnd} options={HOURS.slice(1).map((h) => ({ value: h, label: hour(h) }))} /></label>
      <label className={styles.field}><span>{t('em.timezone')}</span>
        <input className={styles.input} list="em-zones" value={tz} onChange={(e) => setTz(e.target.value)} />
        <datalist id="em-zones">{zones.map((z) => <option key={z} value={z} />)}</datalist></label>
      <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={!Number(limit) || start >= end} onClick={save}>{t('em.savePrefs')}</button>
      <p className={`${styles.muted} ${local.span}`}>{t('em.limitWhy')}</p>
    </div>
  )
}

/** Settings → Email sending: the organisation's own Resend account, sandbox or live. */
export default function EmailSendingSettings() {
  const { t, i18n } = useTranslation()
  const { active, can } = useOrg()
  const canManage = !!active && can('manage', active.id)
  const [status, setStatus] = useState<EmailStatus | null>(null)
  const [reconnecting, setReconnecting] = useState(false)
  const [confirmOff, setConfirmOff] = useState(false)

  const load = useCallback(async () => {
    if (!active) return
    const { data, error } = await supabase.rpc('email_status', { p_org: active.id })
    if (toastFailure(t, error)) return
    setStatus(data as EmailStatus)
    setReconnecting(false)
  }, [active, t])
  useEffect(() => { load() }, [load])

  async function disconnect() {
    if (!active) return
    const { error } = await supabase.rpc('disconnect_email', { p_org: active.id })
    if (toastFailure(t, error)) return
    toast.success(t('em.disconnected'))
    setConfirmOff(false)
    load()
  }

  async function resume() {
    if (!active) return
    const { error } = await supabase.rpc('resume_email', { p_org: active.id })
    if (toastFailure(t, error)) return
    toast.success(t('em.resumed'))
    load()
  }

  if (!active || !status) return null
  const joinUrl = `${window.location.origin}/join/${status.slug}`
  const since = status.connected_at ? new Date(status.connected_at).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' }) : ''

  return (
    <div className={local.wrap} data-testid="email-sending">
      {status.connected ? (
        <div className={local.status}>
          <p className={local.headline}>
            <span className={`${local.badge} ${status.mode === 'live' ? local.live : ''}`}>{t(`em.mode.${status.mode}`)}</span>
            {status.mode === 'live'
              ? t('em.liveLine', { from: `${status.from_name} <${status.from_email}>` })
              : t('em.sandboxLine', { to: status.sandbox_to })}
          </p>
          <p className={styles.muted}>{t('em.since', { when: since })} · {status.webhook ? t('em.webhookOn') : t('em.webhookOff')}</p>
          {status.paused_reason && (
            <div className={local.paused} role="alert">
              <p className={local.warn}>{t('em.paused', { why: status.paused_reason })}</p>
              <p className={styles.muted}>{t('em.pausedWhat')}</p>
              {canManage && <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={resume}>{t('em.resume')}</button>}
            </div>
          )}
          <div className={local.join}>
            <span>{t('em.joinLink')}</span>
            <code>{joinUrl}</code>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => navigator.clipboard?.writeText(joinUrl).then(() => toast.success(t('em.copied')))}>
              {t('em.copy')}
            </button>
          </div>
          {canManage && <Preferences orgId={active.id} status={status} onDone={load} />}
          {canManage && !reconnecting && (
            <div className={local.actions}>
              <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => setReconnecting(true)}>{t('em.reconnect')}</button>
              <button type="button" className={`${styles.btn} ${styles.danger}`} onClick={() => (confirmOff ? disconnect() : setConfirmOff(true))}>
                {confirmOff ? t('em.disconnectConfirm') : t('em.disconnect')}
              </button>
            </div>
          )}
        </div>
      ) : (
        <p className={styles.muted}>{t('em.notConnected')}</p>
      )}
      {canManage && (!status.connected || reconnecting) && (
        <Connect orgId={active.id} orgName={active.name} hasAddress={status.postal_address} onDone={load} />
      )}
      {!canManage && !status.connected && <p className={styles.muted}>{t('em.askManager')}</p>}
    </div>
  )
}
