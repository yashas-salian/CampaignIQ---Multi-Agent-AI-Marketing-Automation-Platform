import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams, useSearchParams } from 'react-router-dom'

import { supabase } from '../lib/supabaseClient'
import local from './EmailPublic.module.css'

interface Info { brand: string; slug: string; privacy_url: string | null; brand_color: string | null; open: boolean }

/**
 * A brand's public sign-up form (linked from its campaign posts). For the
 * brand's future customers, not CampaignIQ users: no app chrome. Signing up
 * only sends a confirmation email; the person is subscribed when they click it.
 */
export default function Join() {
  const { t, i18n } = useTranslation()
  const { slug = '' } = useParams()
  const [params] = useSearchParams()
  const [info, setInfo] = useState<Info | null>(null)
  const [state, setState] = useState<'loading' | 'form' | 'sent' | 'closed' | 'missing' | 'limited' | 'error'>('loading')
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [company, setCompany] = useState('') // hidden: only bots fill it
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    supabase.functions.invoke('join', { body: { action: 'info', slug } }).then(({ data, error }) => {
      if (error || !data) return setState('missing')
      setInfo(data as Info)
      setState((data as Info).open ? 'form' : 'closed')
    })
  }, [slug])

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!info) return
    setBusy(true)
    const { data, error, response } = await supabase.functions.invoke('join', {
      body: { action: 'signup', slug, email: email.trim(), first_name: firstName.trim() || undefined, language: i18n.language.slice(0, 2),
        c: params.get('c') ?? undefined, consent_text: t('pub.consent', { brand: info.brand }), company },
    })
    setBusy(false)
    if (response?.status === 429) return setState('limited')
    if (error) return setState('error')
    setState((data as { status: string }).status === 'closed' ? 'closed' : 'sent')
  }

  return (
    <main className={local.page}>
      <section className={local.card} aria-live="polite">
        {info && <p className={local.brand} style={info.brand_color ? { color: info.brand_color } : undefined}>{info.brand}</p>}
        {state === 'loading' && <p className={local.muted}>…</p>}
        {state === 'missing' && <><h1>{t('pub.joinMissingTitle')}</h1><p>{t('pub.joinMissingBody')}</p></>}
        {state === 'closed' && info && <><h1>{t('pub.joinClosedTitle')}</h1><p>{t('pub.joinClosedBody', { brand: info.brand })}</p></>}
        {state === 'sent' && <><h1>{t('pub.checkInboxTitle')}</h1><p>{t('pub.checkInboxBody', { email: email.trim() })}</p></>}
        {state === 'limited' && <p role="alert">{t('pub.limited')}</p>}
        {(state === 'form' || state === 'error') && info && (
          <form className={local.form} onSubmit={submit}>
            <h1>{t('pub.joinTitle', { brand: info.brand })}</h1>
            <p>{t('pub.joinBody', { brand: info.brand })}</p>
            <label className={local.field}><span>{t('pub.email')}</span>
              <input className={local.input} type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
            <label className={local.field}><span>{t('pub.firstName')}</span>
              <input className={local.input} autoComplete="given-name" maxLength={80} value={firstName} onChange={(e) => setFirstName(e.target.value)} /></label>
            <label className={local.trap} aria-hidden="true">Company
              <input tabIndex={-1} autoComplete="off" value={company} onChange={(e) => setCompany(e.target.value)} /></label>
            <p className={local.consent}>{t('pub.consent', { brand: info.brand })}</p>
            <button type="submit" className={local.button} disabled={busy || !email.trim()}>{t('pub.joinButton')}</button>
            {state === 'error' && <p role="alert">{t('pub.tryAgain')}</p>}
            {info.privacy_url && <a className={local.small} href={info.privacy_url} target="_blank" rel="noreferrer">{t('pub.privacy', { brand: info.brand })}</a>}
          </form>
        )}
      </section>
      <p className={local.powered}>{t('pub.powered')}</p>
    </main>
  )
}
