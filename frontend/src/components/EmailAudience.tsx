import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Select from './Select'
import { toastFailure } from '../lib/notify'
import { useDescribe } from '../lib/segments'
import { toast } from '../lib/toast'
import { supabase } from '../lib/supabaseClient'
import type { AudienceProgress, Campaign, EmailRoundStats, EmailStatus, Segment } from '../lib/types'
import styles from '../styles/app.module.css'
import local from './EmailAudience.module.css'

const MIN_BATCH = 20 // src/capabilities/email_engine.py batch_size()

/** About how many people the next round emails: what's left spread over the rounds left, never below 20. */
function nextBatch(remaining: number, roundsLeft: number) {
  return remaining <= MIN_BATCH ? remaining : Math.max(Math.ceil(remaining / Math.max(roundsLeft, 1)), MIN_BATCH)
}

/**
 * Who the campaign emails. Before Gate 1 is approved: pick a saved segment
 * (with how many people it reaches now). After: the audience is fixed, and this
 * shows how far the batches have got and how each round's emails did; at Gate
 * 2 (`gate2`) also the coming batch and a test send. Without a connected Resend
 * account, the campaign emails the test inbox only, and this says so.
 */
export default function EmailAudience({ campaign, editable, gate2 = false, onChanged }: {
  campaign: Campaign; editable: boolean; gate2?: boolean; onChanged?: () => void
}) {
  const { t } = useTranslation()
  const describe = useDescribe()
  const [status, setStatus] = useState<EmailStatus | null>(null)
  const [segments, setSegments] = useState<Segment[]>([])
  const [count, setCount] = useState<number | null>(null)
  const [progress, setProgress] = useState<AudienceProgress | null>(null)
  const [rounds, setRounds] = useState<EmailRoundStats[]>([])
  const [testing, setTesting] = useState(false)
  const frozen = !!campaign.email_audience_frozen_at
  const chosen = segments.find((s) => s.id === campaign.segment_id) ?? null

  const load = useCallback(async () => {
    const [st, segs] = await Promise.all([
      supabase.rpc('email_status', { p_org: campaign.org_id }),
      supabase.from('segments').select('id,org_id,name,filter,created_at').eq('org_id', campaign.org_id).order('created_at'),
    ])
    setStatus((st.data as EmailStatus) ?? null)
    setSegments((segs.data as Segment[]) ?? [])
    if (frozen) {
      const [p, r] = await Promise.all([
        supabase.rpc('audience_progress', { p_campaign: campaign.id }), supabase.rpc('email_round_stats', { p_campaign: campaign.id }),
      ])
      setProgress((p.data as AudienceProgress) ?? null)
      setRounds((r.data as EmailRoundStats[]) ?? [])
    }
  }, [campaign.org_id, campaign.id, frozen])
  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (frozen || !chosen) return setCount(null)
    supabase.rpc('segment_count', { p_org: campaign.org_id, p_filter: chosen.filter, p_language: campaign.target_language })
      .then(({ data }) => setCount(typeof data === 'number' ? data : null))
  }, [frozen, chosen, campaign.org_id, campaign.target_language])

  async function toggleLink(on: boolean) {
    const { error } = await supabase.rpc('set_campaign_signup_link', { p_campaign: campaign.id, p_on: on })
    if (toastFailure(t, error)) return
    onChanged?.()
  }

  async function useSuggestion() {
    const { error } = await supabase.rpc('accept_email_suggestion', { p_campaign: campaign.id })
    if (toastFailure(t, error)) return
    onChanged?.()
  }

  async function sendTest() {
    setTesting(true)
    const { data, error } = await supabase.functions.invoke('email-test', { body: { campaign_id: campaign.id } })
    setTesting(false)
    if (toastFailure(t, error)) return
    toast.success(t('aud.testSent', { to: (data as { sent_to: string }).sent_to }))
  }

  async function pick(id: string) {
    const { error } = await supabase.rpc('set_campaign_segment', { p_campaign: campaign.id, p_segment: id || null })
    if (toastFailure(t, error)) return
    onChanged?.()
  }

  if (!status) return null
  if (!status.connected) {
    return <p className={local.note} data-testid="email-audience">{t('aud.notConnected')} <Link to="/settings#email">{t('aud.connect')}</Link></p>
  }

  return (
    <div className={local.wrap} data-testid="email-audience">
      <div className={local.head}>
        <strong>{t('aud.title')}</strong>
        {status.mode === 'sandbox' && <span className={local.badge}>{t('aud.sandbox', { to: status.sandbox_to })}</span>}
      </div>
      {frozen ? (
        progress && progress.total > 0 ? (
          <p className={local.line}>
            {t('aud.progress', { name: chosen?.name ?? t('aud.segment'), total: progress.total - progress.holdout, emailed: progress.emailed,
              remaining: progress.remaining })}
            {(progress.waiting ?? 0) > 0 && ` · ${t('aud.waiting', { count: progress.waiting })}`}
            {progress.holdout > 0 && ` · ${t('aud.holdout', { count: progress.holdout })}`}
            {progress.excluded > 0 && ` · ${t('aud.excluded', { count: progress.excluded })}`}
          </p>
        ) : (
          <p className={local.line}>{t('aud.none')}</p>
        )
      ) : editable ? (
        <>
          {campaign.email_suggestion && (
            <div className={local.suggestion} data-testid="email-suggestion">
              <p className={local.line}>
                <strong>{t('aud.suggested')}</strong> {describe(campaign.email_suggestion.filter)} · {t('seg.count', { count: campaign.email_suggestion.people })}
              </p>
              {campaign.email_suggestion.reason && <p className={local.hint}>{campaign.email_suggestion.reason}</p>}
              <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={useSuggestion}>{t('aud.useSuggestion')}</button>
            </div>
          )}
          <Select aria-label={t('aud.title')} value={campaign.segment_id ?? ''} onChange={pick}
            options={[{ value: '', label: t('aud.noEmail') }, ...segments.map((s) => ({ value: s.id, label: s.name }))]} />
          {chosen && (
            <p className={local.line}>{describe(chosen.filter)} · <strong>{count === null ? '…' : t('seg.count', { count })}</strong></p>
          )}
          <p className={local.hint}>{t('aud.hint')} <Link to="/contacts#segments">{t('aud.manage')}</Link></p>
          <label className={local.check}>
            <input type="checkbox" checked={campaign.signup_link !== false} onChange={(e) => toggleLink(e.target.checked)} />
            <span>{t('aud.signupLink')}</span>
          </label>
        </>
      ) : (
        <p className={local.line}>{chosen ? `${chosen.name} · ${describe(chosen.filter)}` : t('aud.noEmail')}</p>
      )}
      {frozen && progress && Object.keys(progress.excluded_by ?? {}).length > 0 && (
        <p className={local.hint}>
          {t('aud.leftBecause')} {Object.entries(progress.excluded_by ?? {}).map(([why, n]) => t(`aud.why.${why}`, { count: n, defaultValue: `${n} ${why}` })).join(', ')}
        </p>
      )}
      {gate2 && frozen && progress && (
        <p className={local.line} data-testid="next-batch">
          {progress.remaining > 0
            ? t('aud.nextBatch', { count: nextBatch(progress.remaining, (campaign.max_rounds ?? 3) - campaign.current_round + 1) })
            : t('aud.allReached')}
          {status.send_window_start !== null && ` ${t('aud.windowNote', { start: String(status.send_window_start).padStart(2, '0'),
            end: String(status.send_window_end).padStart(2, '0'), tz: status.timezone, limit: status.daily_limit })}`}
        </p>
      )}
      {rounds.length > 0 && (
        <ul className={local.rounds} data-testid="email-rounds">
          {rounds.map((r) => (
            <li key={`${r.round_number}-${r.channel}`}>
              <strong>{t('aud.round', { n: r.round_number })}{r.channel === 'email_b' ? ' (B)' : ''}</strong>{' '}
              {t('aud.roundLine', { sent: r.sent, delivered: r.delivered, bounced: r.bounced, complained: r.complained })}
              {r.waiting > 0 && ` · ${t('aud.waiting', { count: r.waiting })}`}
              {r.sandbox && ` · ${t('aud.sandboxShort')}`}
            </li>
          ))}
        </ul>
      )}
      {gate2 && (
        <button type="button" className={`${styles.btn} ${styles.ghost} ${local.test}`} disabled={testing} onClick={sendTest}>{t('aud.sendTest')}</button>
      )}
    </div>
  )
}
