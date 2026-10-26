import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { toastFailure } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import styles from '../styles/app.module.css'
import local from './ContactDetail.module.css'

interface Consent {
  consent_source: string
  consent_note: string | null
  consent_text: string
  consent_at: string
  confirmed_at: string | null
}
interface ContactEvent { id: number; kind: string; actor: string; created_at: string }

/** One contact's consent record and history; owners and admins can erase them. */
export default function ContactDetail({ id, canErase, onErased }: { id: string; canErase: boolean; onErased: () => void }) {
  const { t, i18n } = useTranslation()
  const [consent, setConsent] = useState<Consent | null>(null)
  const [events, setEvents] = useState<ContactEvent[]>([])
  const [confirmErase, setConfirmErase] = useState(false)
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })

  useEffect(() => {
    Promise.all([
      supabase.from('contacts').select('consent_source,consent_note,consent_text,consent_at,confirmed_at').eq('id', id).maybeSingle(),
      supabase.from('contact_events').select('id,kind,actor,created_at').eq('contact_id', id).order('created_at', { ascending: false }).limit(50),
    ]).then(([c, e]) => {
      setConsent((c.data as Consent | null) ?? null)
      setEvents((e.data as ContactEvent[]) ?? [])
    })
  }, [id])

  async function erase() {
    const { error } = await supabase.rpc('erase_contact', { p_contact: id })
    if (toastFailure(t, error)) return
    toast.success(t('ct.erased'))
    onErased()
  }

  return (
    <div className={local.detail} data-testid="contact-detail">
      {consent && (
        <dl className={local.consent}>
          <div><dt>{t('ct.consentHow')}</dt><dd>{t(`ct.source.${consent.consent_source}`)}{consent.consent_note ? ` · ${consent.consent_note}` : ''}</dd></div>
          <div><dt>{t('ct.consentWhen')}</dt><dd>{when(consent.consent_at)}{consent.confirmed_at ? ` · ${t('ct.confirmedAt', { when: when(consent.confirmed_at) })}` : ''}</dd></div>
          <div className={local.wide}><dt>{t('ct.consentWording')}</dt><dd>“{consent.consent_text}”</dd></div>
        </dl>
      )}
      {events.length > 0 && (
        <ol className={local.history} aria-label={t('ct.history')}>
          {events.map((e) => (
            <li key={e.id}><span>{t(`ct.event.${e.kind}`, e.kind)}</span><span className={local.meta}>{t(`ct.actor.${e.actor}`, e.actor)} · {when(e.created_at)}</span></li>
          ))}
        </ol>
      )}
      {canErase && (
        <div className={local.erase}>
          <button type="button" className={`${styles.btn} ${confirmErase ? styles.dangerSolid : styles.danger}`}
            onClick={() => (confirmErase ? erase() : setConfirmErase(true))}>
            {confirmErase ? t('ct.eraseConfirm') : t('ct.erase')}
          </button>
          <span className={local.meta}>{t('ct.eraseWhat')}</span>
        </div>
      )}
    </div>
  )
}
