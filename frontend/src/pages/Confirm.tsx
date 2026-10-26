import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { supabase } from '../lib/supabaseClient'
import local from './EmailPublic.module.css'

/** The link in a sign-up confirmation email: one click, and the person is subscribed. */
export default function Confirm() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [brand, setBrand] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'done' | 'missing'>('loading')

  useEffect(() => {
    if (!/^[0-9a-f]{32}$/.test(token)) {
      setState('missing')
      return
    }
    supabase.functions.invoke('join', { body: { action: 'confirm', token } }).then(({ data, error }) => {
      if (error || !data) return setState('missing')
      setBrand((data as { brand: string }).brand)
      setState('done')
    })
  }, [token])

  return (
    <main className={local.page}>
      <section className={local.card} aria-live="polite">
        {brand && <p className={local.brand}>{brand}</p>}
        {state === 'loading' && <p className={local.muted}>…</p>}
        {state === 'done' && <><h1>{t('pub.confirmedTitle')}</h1><p>{t('pub.confirmedBody', { brand })}</p></>}
        {state === 'missing' && <><h1>{t('pub.confirmMissingTitle')}</h1><p>{t('pub.confirmMissingBody')}</p></>}
      </section>
      <p className={local.powered}>{t('pub.powered')}</p>
    </main>
  )
}
