import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { Campaign, CampaignHold } from '../lib/types'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'
import app from '../styles/app.module.css'
import styles from './CircuitBreaker.module.css'

function ago(iso: string | null | undefined, lang: string): string {
  if (!iso) return ''
  const mins = Math.round((new Date(iso).getTime() - Date.now()) / 60000)
  const fmt = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  if (Math.abs(mins) < 60) return fmt.format(mins, 'minute')
  if (Math.abs(mins) < 1440) return fmt.format(Math.round(mins / 60), 'hour')
  return fmt.format(Math.round(mins / 1440), 'day')
}

/** What the hold saw: headlines, the link, lapsed approvers or the rule findings. */
function Evidence({ hold }: { hold: CampaignHold }) {
  const { t } = useTranslation()
  const e = hold.evidence ?? {}
  const headlines = Array.isArray(e.headlines) ? (e.headlines as string[]) : []
  const findings = Array.isArray(e.findings) ? (e.findings as { problem: string }[]) : []
  return (
    <>
      {typeof e.url === 'string' && (
        <p className={styles.evidence}>
          {t('circuit.link')}: <code>{e.url}</code>
        </p>
      )}
      {headlines.length > 0 && (
        <ul className={styles.list}>
          {headlines.map((h, i) => (
            <li key={i}>“{h}”</li>
          ))}
        </ul>
      )}
      {findings.length > 0 && (
        <ul className={styles.list}>
          {findings.map((f, i) => (
            <li key={i}>{f.problem}</li>
          ))}
        </ul>
      )}
    </>
  )
}

function HoldCard({ hold, canResume, onDone }: { hold: CampaignHold; canResume: boolean; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  async function resolve(falseAlarm: boolean) {
    setBusy(true)
    const { error } = await supabase.rpc('resolve_hold', { p_hold: hold.id, p_note: note.trim(), p_false_alarm: falseAlarm })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t(falseAlarm ? 'circuit.falseAlarmToast' : 'circuit.resumedToast'))
    setNote('')
    onDone()
  }

  return (
    <li className={`${styles.hold} ${hold.severity === 'critical' ? styles.critical : styles.warning}`}>
      <div className={styles.holdTop}>
        <strong>{t(`circuit.trigger.${hold.trigger}`)}</strong>
        <span className={styles.chip}>{hold.channel ? t('circuit.channel', { channel: hold.channel }) : t('circuit.allChannels')}</span>
        <span className={styles.when}>
          {t('circuit.detected', { when: ago(hold.created_at, i18n.language) })}
          {hold.signal_at && hold.signal_at !== hold.created_at ? ` · ${t('circuit.observed', { when: ago(hold.signal_at, i18n.language) })}` : ''}
        </span>
      </div>
      <p className={styles.detail}>{hold.detail}</p>
      <Evidence hold={hold} />
      <p className={styles.advice}>{t(`circuit.advice.${hold.trigger}`)}</p>
      {canResume ? (
        <div className={styles.resolve}>
          <label className={app.field}>
            <span>{t('circuit.noteLabel')}</span>
            <textarea className={app.textarea} rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('circuit.notePlaceholder')} />
          </label>
          <div className={styles.buttons}>
            <button type="button" className={`${app.btn} ${app.primary}`} disabled={busy || note.trim().length < 10} onClick={() => resolve(false)}>
              {t('circuit.resume')}
            </button>
            <button type="button" className={`${app.btn} ${app.ghost}`} disabled={busy || note.trim().length < 10} onClick={() => resolve(true)}>
              {t('circuit.falseAlarm')}
            </button>
          </div>
        </div>
      ) : (
        <p className={styles.muted}>{t('circuit.onlyManagers')}</p>
      )}
    </li>
  )
}

/** The campaign is paused: what tripped, the evidence, and (owners/admins) how to resume. Leads the page. */
export function PausedPanel({ campaign, holds, canResume, onDone }: { campaign: Campaign; holds: CampaignHold[]; canResume: boolean; onDone: () => void }) {
  const { t, i18n } = useTranslation()
  const active = holds.filter((h) => h.status === 'active')
  if (!active.length) return null
  const paused = active.some((h) => h.severity === 'critical')
  return (
    <section className={`${app.panel} ${styles.panel} ${paused ? styles.pausedPanel : ''}`} aria-live="polite" data-testid="paused-panel">
      <div className={styles.head}>
        <span className={styles.icon} aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <rect x="6" y="5" width="4" height="14" rx="1" fill="currentColor" />
            <rect x="14" y="5" width="4" height="14" rx="1" fill="currentColor" />
          </svg>
        </span>
        <div>
          <h2>{paused ? t('circuit.pausedTitle') : t('circuit.warningTitle')}</h2>
          <p className={app.panelSub}>
            {paused ? t('circuit.pausedBody', { since: ago(campaign.paused_at, i18n.language) }) : t('circuit.warningBody')}
          </p>
        </div>
      </div>
      <ul className={styles.holds}>
        {active.map((h) => (
          <HoldCard key={h.id} hold={h} canResume={canResume} onDone={onDone} />
        ))}
      </ul>
      <p className={styles.muted}>{t('circuit.publishedNote')}</p>
    </section>
  )
}

/** Safety controls for a running campaign: the offer's end date, an emergency stop, revoking the live approval, and past holds. */
export function SafetyControls({ campaign, holds, canStop, canEdit, onDone }: {
  campaign: Campaign
  holds: CampaignHold[]
  canStop: boolean
  canEdit: boolean
  onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const [offerEnds, setOfferEnds] = useState(() => (campaign.offer_ends_at ? toLocalInput(campaign.offer_ends_at) : ''))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const past = holds.filter((h) => h.status !== 'active')
  const live = ['awaiting_metrics', 'awaiting_next_round'].includes(campaign.status)

  async function saveOffer() {
    setBusy(true)
    const { error } = await supabase.rpc('set_offer_end', { p_campaign: campaign.id, p_ends_at: offerEnds ? new Date(offerEnds).toISOString() : null })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('circuit.offerSaved'))
    onDone()
  }

  async function stop(kind: 'emergency_stop' | 'revoke_approval') {
    setBusy(true)
    const { error } = await supabase.rpc(kind, { p_campaign: campaign.id, p_reason: reason.trim() })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t(kind === 'emergency_stop' ? 'circuit.stoppedToast' : 'circuit.revokedToast'))
    setReason('')
    onDone()
  }

  return (
    <section className={`${app.panel} ${styles.panel}`} data-testid="safety-controls">
      <div className={app.panelHead}>
        <h2>{t('circuit.controlsTitle')}</h2>
      </div>
      <div className={styles.controls}>
        <div className={styles.control}>
          <label className={app.field}>
            <span>{t('circuit.offerEnds')}</span>
            <input type="datetime-local" className={app.input} value={offerEnds} disabled={!canEdit} onChange={(e) => setOfferEnds(e.target.value)} />
          </label>
          <small className={styles.muted}>{t('circuit.offerHint')}</small>
          {canEdit && (
            <button type="button" className={`${app.btn} ${app.ghost}`} disabled={busy} onClick={saveOffer}>
              {t('circuit.saveOffer')}
            </button>
          )}
        </div>
        <div className={styles.control}>
          <label className={app.field}>
            <span>{t('circuit.reasonLabel')}</span>
            <textarea className={app.textarea} rows={2} value={reason} disabled={!canStop} onChange={(e) => setReason(e.target.value)} placeholder={t('circuit.reasonPlaceholder')} />
          </label>
          {canStop ? (
            <div className={styles.buttons}>
              <button type="button" className={`${app.btn} ${app.dangerSolid}`} disabled={busy || reason.trim().length < 10} onClick={() => stop('emergency_stop')}>
                {t('circuit.emergencyStop')}
              </button>
              {live && (
                <button type="button" className={`${app.btn} ${app.danger}`} disabled={busy || reason.trim().length < 10} onClick={() => stop('revoke_approval')}>
                  {t('circuit.revoke')}
                </button>
              )}
            </div>
          ) : (
            <small className={styles.muted}>{t('circuit.cantStop')}</small>
          )}
        </div>
      </div>
      {past.length > 0 && (
        <details className={styles.history}>
          <summary>{t('circuit.history', { count: past.length })}</summary>
          <ul className={styles.list}>
            {past.map((h) => (
              <li key={h.id}>
                <strong>{t(`circuit.trigger.${h.trigger}`)}</strong> · {t(`circuit.status.${h.status}`)} {ago(h.resolved_at, i18n.language)}
                {h.resolution_note ? ` — “${h.resolution_note}”` : ''}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function toLocalInput(iso: string): string {
  const d = new Date(iso)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}
