import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'

/** GDPR self-service: download everything about me, or delete my account. */
export default function PrivacySettings() {
  const { t } = useTranslation()
  const [busy, setBusy] = useState<'export' | 'delete' | null>(null)
  const [confirmText, setConfirmText] = useState('')
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null)

  async function exportData() {
    setBusy('export')
    setMessage(null)
    const { data, error } = await supabase.rpc('export_my_data')
    setBusy(null)
    if (error || !data) {
      setMessage({ ok: false, text: error?.message ?? t('privacy.exportFailed') })
      return
    }
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const a = Object.assign(document.createElement('a'), { href: url, download: `marketingos-data-${new Date().toISOString().slice(0, 10)}.json` })
    a.click()
    URL.revokeObjectURL(url)
  }

  async function deleteAccount() {
    setBusy('delete')
    setMessage(null)
    const { error, response } = await supabase.functions.invoke('delete-account', { body: { confirm: 'DELETE' } })
    if (error) {
      // 409 carries the reason (e.g. last owner of a team) in the body.
      const body = response ? ((await response.json().catch(() => null)) as { error?: string } | null) : null
      setMessage({ ok: false, text: body?.error ?? error.message })
      setBusy(null)
      return
    }
    await supabase.auth.signOut()
  }

  return (
    <div className={local.team}>
      <div>
        <p className={styles.muted}>{t('privacy.exportBody')}</p>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} style={{ marginTop: 12 }} disabled={busy !== null} onClick={exportData}>
          {busy === 'export' && <span className={styles.spinner} aria-hidden="true" />}
          {t('privacy.export')}
        </button>
      </div>

      <div className={local.policy}>
        <h3 className={local.subhead}>{t('privacy.deleteTitle')}</h3>
        <p className={styles.muted}>{t('privacy.deleteBody')}</p>
        <div className={local.inline}>
          <label className={styles.field}>
            <span>{t('privacy.confirmLabel')}</span>
            <input className={styles.input} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} placeholder="DELETE" autoComplete="off" />
          </label>
          <button type="button" className={`${styles.btn} ${styles.danger}`} disabled={confirmText !== 'DELETE' || busy !== null} onClick={deleteAccount}>
            {busy === 'delete' && <span className={styles.spinner} aria-hidden="true" />}
            {t('privacy.delete')}
          </button>
        </div>
      </div>

      {message && (
        <p className={message.ok ? styles.muted : local.error} role="alert">
          {message.text}
        </p>
      )}
    </div>
  )
}
