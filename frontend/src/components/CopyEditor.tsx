import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './Collab.module.css'
import { toast } from '../lib/toast'
import { toastFailure, toastLoadError } from '../lib/notify'

interface Revision {
  id: number
  copy_text: string
  edited_by: string | null
  created_at: string
}

/**
 * Gate 2: approvers can rewrite a variant's copy before approving. Every save
 * is a new version (the AI's draft is kept as version 1) and any version can
 * be restored. The database only accepts edits while Gate 2 is open.
 */
export default function CopyEditor({ campaignId, round, variant, text, people, onSaved }: {
  campaignId: string
  round: number
  variant: 'a' | 'b'
  text: string
  people: Record<string, string>
  onSaved: () => void
}) {
  const { t, i18n } = useTranslation()
  const [draft, setDraft] = useState(text)
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from('copy_revisions')
      .select('id,copy_text,edited_by,created_at')
      .eq('campaign_id', campaignId)
      .eq('round_number', round)
      .eq('variant', variant)
      .order('id', { ascending: false })
    if (toastLoadError(t, error, () => load())) return
    setRevisions((data as Revision[] | null) ?? [])
  }, [campaignId, round, variant, t])

  useEffect(() => {
    load()
  }, [load])
  useEffect(() => setDraft(text), [text])

  async function save(next: string) {
    setBusy(true)
    const { error: err } = await supabase.rpc('edit_round_copy', { p_campaign: campaignId, p_round: round, p_variant: variant, p_text: next })
    setBusy(false)
    if (toastFailure(t, err)) return
    toast.success(next === text ? t('toast.copyRestored') : t('toast.copySaved'))
    await load()
    onSaved()
  }

  const when = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'short', timeStyle: 'short' })
  return (
    <div className={local.editor}>
      <label className={styles.field}>
        <span>{variant === 'a' ? t('collab.editCopy') : t('collab.editCopyB')}</span>
        <textarea className={styles.textarea} rows={3} maxLength={3000} value={draft} onChange={(e) => setDraft(e.target.value)} />
      </label>
      <div className={local.commentActions}>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy || draft.trim() === text.trim() || !draft.trim()} onClick={() => save(draft)}>
          {t('collab.saveEdit')}
        </button>
      </div>
      {revisions.length > 0 && (
        <details className={local.history}>
          <summary>{t('collab.history', { count: revisions.length })}</summary>
          <ol>
            {revisions.map((r) => (
              <li key={r.id}>
                <div className={local.commentHead}>
                  <strong>{r.edited_by ? (people[r.edited_by] ?? r.edited_by.slice(0, 8)) : t('collab.ai')}</strong>
                  <time dateTime={r.created_at}>{when.format(new Date(r.created_at))}</time>
                  {r.copy_text !== text && (
                    <button type="button" className={local.linkBtn} disabled={busy} onClick={() => save(r.copy_text)}>
                      {t('collab.restore')}
                    </button>
                  )}
                </div>
                <p>{r.copy_text}</p>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  )
}
