import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'
import styles from '../styles/app.module.css'

// Matches MAX_REPAINTS in src/scheduler/run_capability.py.
export const MAX_REPAINTS = 5
const POLL_MS = 4000
const GIVE_UP_MS = 6 * 60 * 1000

/**
 * Gate 2's "New picture": repaints the round's ad (same prompt, words, layout
 * and brand) through the "ad_image" capability run, then reloads the page data.
 * Approving afterwards sends the new picture (human_gate.gate_2_node).
 */
export default function NewPicture({ campaignId, round, version, onDone }: {
  campaignId: string
  round: number
  version: number
  onDone: () => void
}) {
  const { t } = useTranslation()
  const [runId, setRunId] = useState<string | null>(null)
  const started = useRef(0)
  const left = Math.max(0, MAX_REPAINTS - version)

  useEffect(() => {
    if (!runId) return
    const timer = window.setInterval(async () => {
      const { data } = await supabase.from('capability_runs').select('status,error').eq('id', runId).maybeSingle()
      const status = (data as { status?: string } | null)?.status
      if (status === 'completed') {
        window.clearInterval(timer)
        setRunId(null)
        onDone()
        toast.success(t('newPicture.done'))
      } else if (status === 'failed' || Date.now() - started.current > GIVE_UP_MS) {
        window.clearInterval(timer)
        setRunId(null)
        toast.error(t('newPicture.failed'))
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [runId, onDone, t])

  async function repaint() {
    const { data, error } = await supabase.functions.invoke('trigger-capability-run', {
      body: { capability: 'ad_image', params: { campaign_id: campaignId, round } },
    })
    if (toastFailure(t, error)) return
    started.current = Date.now()
    setRunId((data as { run_id: string }).run_id)
  }

  return (
    <div>
      <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={!!runId || left === 0} onClick={repaint}>
        {runId && <span className={styles.spinner} aria-hidden="true" />}
        {runId ? t('newPicture.painting') : t('newPicture.button')}
      </button>
      <p className={styles.muted} role="status">
        {runId ? t('newPicture.wait') : left === 0 ? t('newPicture.none') : t('newPicture.left', { count: left })}
      </p>
    </div>
  )
}
