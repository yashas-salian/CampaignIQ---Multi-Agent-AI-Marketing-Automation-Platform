import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'

interface Billing {
  status: string | null
  current_period_end: string | null
  stripe_customer_id: string | null
}

/** Plan and Stripe billing for the active organisation (owners act; admins can see). */
export default function BillingSettings() {
  const { t, i18n } = useTranslation()
  const { active, can } = useOrg()
  const [plan, setPlan] = useState<string>('free')
  const [billing, setBilling] = useState<Billing | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const returned = new URLSearchParams(window.location.search).get('billing')

  useEffect(() => {
    if (!active) return
    supabase.rpc('org_usage', { p_org: active.id }).then(({ data }) => setPlan((data as { plan?: string } | null)?.plan ?? 'free'))
    supabase
      .from('org_billing')
      .select('status,current_period_end,stripe_customer_id')
      .eq('org_id', active.id)
      .maybeSingle()
      .then(({ data }) => setBilling((data as Billing | null) ?? null))
  }, [active])

  async function go(action: 'checkout' | 'portal') {
    if (!active) return
    setBusy(true)
    setError(null)
    const { data, error: err, response } = await supabase.functions.invoke('billing', { body: { action, org_id: active.id } })
    if (err) {
      const body = response ? ((await response.json().catch(() => null)) as { error?: string } | null) : null
      setError(body?.error ?? err.message)
      setBusy(false)
      return
    }
    window.location.href = (data as { url: string }).url
  }

  const owner = can('own')
  const renews = billing?.current_period_end ? new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(billing.current_period_end)) : null
  return (
    <div className={local.team}>
      {returned === 'success' && <p className={styles.muted}>{t('billing.thanks')}</p>}
      <div className={local.member}>
        <div className={local.who}>
          <strong>{t('billing.plan', { plan: plan.toUpperCase() })}</strong>
          <span className={styles.muted}>
            {billing?.status ? t('billing.status', { status: billing.status }) : t('billing.noSub')}
            {renews ? ` · ${t('billing.renews', { date: renews })}` : ''}
          </span>
        </div>
        {owner && plan !== 'pro' && plan !== 'enterprise' && (
          <button type="button" className={`${styles.btn} ${styles.primary} ${local.small}`} disabled={busy} onClick={() => go('checkout')}>
            {t('billing.upgrade')}
          </button>
        )}
        {owner && billing?.stripe_customer_id && (
          <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} disabled={busy} onClick={() => go('portal')}>
            {t('billing.manage')}
          </button>
        )}
      </div>
      <p className={styles.muted}>{owner ? t('billing.testNote') : t('billing.ownersOnly')}</p>
      {error && <p className={local.error} role="alert">{error}</p>}
    </div>
  )
}
