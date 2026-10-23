import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'

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

  // Back from checkout: thank once, then drop the flag so a reload doesn't repeat it.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.get('billing') !== 'success') return
    toast.success(t('billing.thanks'))
    params.delete('billing')
    const query = params.toString()
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}${window.location.hash}`)
  }, [t])

  useEffect(() => {
    if (!active) return
    supabase.rpc('org_usage', { p_org: active.id }).then(({ data, error }) => {
      if (error) toastFailure(t, error)
      else setPlan((data as { plan?: string } | null)?.plan ?? 'free')
    })
    supabase
      .from('org_billing')
      .select('status,current_period_end,stripe_customer_id')
      .eq('org_id', active.id)
      .maybeSingle()
      .then(({ data }) => setBilling((data as Billing | null) ?? null))
  }, [active, t])

  async function go(action: 'checkout' | 'portal') {
    if (!active) return
    setBusy(true)
    const { data, error: err, response } = await supabase.functions.invoke('billing', { body: { action, org_id: active.id } })
    if (err) {
      const body = response ? ((await response.json().catch(() => null)) as { error?: string } | null) : null
      toastFailure(t, body?.error ?? err.message)
      setBusy(false)
      return
    }
    window.location.href = (data as { url: string }).url
  }

  const owner = can('own')
  const renews = billing?.current_period_end ? new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium' }).format(new Date(billing.current_period_end)) : null
  return (
    <div className={local.team}>
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
    </div>
  )
}
