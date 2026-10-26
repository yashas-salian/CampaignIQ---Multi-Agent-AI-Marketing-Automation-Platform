import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { supabase } from '../lib/supabaseClient'
import local from './EmailPublic.module.css'

interface Info { brand: string; slug: string; status: string; language: string | null; privacy_url: string | null }

/**
 * Where the unsubscribe link in a brand's campaign email lands. For the brand's
 * customer, not a CampaignIQ user: no app chrome, in the person's language,
 * one button. Opening the page never unsubscribes by itself (mail scanners
 * open links); Gmail's one-click unsubscribe goes straight to the function.
 */
export default function Unsubscribe() {
  const { i18n } = useTranslation()
  const [params] = useSearchParams()
  const token = params.get('t') ?? ''
  const [info, setInfo] = useState<Info | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'done' | 'resent' | 'erased' | 'missing' | 'error'>('loading')
  const [confirmErase, setConfirmErase] = useState(false)
  const t = i18n.getFixedT(info?.language ?? i18n.language)

  useEffect(() => {
    if (!/^[0-9a-f]{32}$/.test(token)) {
      setState('missing')
      return
    }
    supabase.functions.invoke('unsubscribe', { body: { t: token, action: 'info' } }).then(({ data, error }) => {
      if (error || !data) return setState('missing')
      setInfo(data as Info)
      setState((data as Info).status === 'subscribed' || (data as Info).status === 'pending' ? 'ready' : 'done')
    })
  }, [token])

  async function resubscribe() {
    const { error } = await supabase.functions.invoke('join', { body: { action: 'resubscribe', t: token } })
    setState(error ? 'error' : 'resent')
  }

  async function erase() {
    const { error } = await supabase.functions.invoke('unsubscribe', { body: { t: token, action: 'erase' } })
    setState(error ? 'error' : 'erased')
  }

  async function unsubscribe() {
    const { error } = await supabase.functions.invoke('unsubscribe', { body: { t: token, action: 'unsubscribe' } })
    setState(error ? 'error' : 'done')
  }

  return (
    <main className={local.page}>
      <section className={local.card} aria-live="polite">
        {info && <p className={local.brand}>{info.brand}</p>}
        {state === 'loading' && <p className={local.muted}>…</p>}
        {state === 'missing' && (
          <>
            <h1>{t('pub.unsubMissingTitle')}</h1>
            <p>{t('pub.unsubMissingBody')}</p>
          </>
        )}
        {state === 'ready' && info && (
          <>
            <h1>{t('pub.unsubTitle', { brand: info.brand })}</h1>
            <p>{t('pub.unsubBody', { brand: info.brand })}</p>
            <button type="button" className={local.button} onClick={unsubscribe}>{t('pub.unsubButton')}</button>
          </>
        )}
        {state === 'done' && info && (
          <>
            <h1>{t('pub.unsubDoneTitle')}</h1>
            <p>{t('pub.unsubDoneBody', { brand: info.brand })}</p>
            <button type="button" className={local.secondary} onClick={resubscribe}>{t('pub.resubscribe')}</button>
            <button type="button" className={local.secondary} onClick={() => (confirmErase ? erase() : setConfirmErase(true))}>
              {confirmErase ? t('pub.eraseConfirm', { brand: info.brand }) : t('pub.erase')}
            </button>
          </>
        )}
        {state === 'erased' && info && <><h1>{t('pub.erasedTitle')}</h1><p>{t('pub.erasedBody', { brand: info.brand })}</p></>}
        {state === 'resent' && <><h1>{t('pub.checkInboxTitle')}</h1><p>{t('pub.resubscribeSent')}</p></>}
        {state === 'error' && <p role="alert">{t('pub.tryAgain')}</p>}
        {info?.privacy_url && <a className={local.small} href={info.privacy_url} target="_blank" rel="noreferrer">{t('pub.privacy', { brand: info.brand })}</a>}
      </section>
      <p className={local.powered}>{t('pub.powered')}</p>
    </main>
  )
}
