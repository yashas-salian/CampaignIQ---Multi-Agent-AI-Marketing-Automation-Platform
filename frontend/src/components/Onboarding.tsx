import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { usernameOf } from '../lib/profile'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './Onboarding.module.css'

interface Step {
  id: string
  done: boolean
  to: string
}

const dismissKey = (userId: string) => `mos.onboardingDismissed.${userId}`

/** First-run checklist. Each step is worked out from real data, not clicks. */
export default function Onboarding({ campaignCount }: { campaignCount: number }) {
  const { t } = useTranslation()
  const { session } = useSession()
  const { active, orgs } = useOrg()
  const [steps, setSteps] = useState<Step[] | null>(null)
  const [dismissed, setDismissed] = useState(() => {
    try {
      return session ? localStorage.getItem(dismissKey(session.user.id)) === '1' : false
    } catch {
      return false
    }
  })

  useEffect(() => {
    if (!session || !active || dismissed) return
    Promise.all([
      supabase.from('gate_approvals').select('gate_decision_id', { count: 'exact', head: true }).eq('user_id', session.user.id),
      supabase.from('brand_kits').select('org_id', { count: 'exact', head: true }).eq('org_id', active.id),
      supabase.from('api_keys').select('id', { count: 'exact', head: true }).eq('org_id', active.id),
      supabase.from('org_settings').select('slack_webhook_url').eq('org_id', active.id).maybeSingle(),
    ]).then(([votes, kit, keys, settings]) => {
      setSteps([
        { id: 'username', done: Boolean(usernameOf(session.user)), to: '/settings#account' },
        { id: 'campaign', done: campaignCount > 0, to: '/dashboard' },
        { id: 'gate', done: (votes.count ?? 0) > 0, to: '/calendar' },
        { id: 'brand', done: (kit.count ?? 0) > 0, to: '/settings#brand' },
        { id: 'team', done: orgs.some((o) => !o.personal), to: '/settings#team' },
        {
          id: 'connect',
          done: (keys.count ?? 0) > 0 || Boolean((settings.data as { slack_webhook_url?: string } | null)?.slack_webhook_url),
          to: '/settings#api',
        },
      ])
    })
  }, [session, active, orgs, campaignCount, dismissed])

  if (!session || dismissed || !steps || steps.every((s) => s.done)) return null
  const done = steps.filter((s) => s.done).length

  return (
    <section className={`${styles.panel} ${local.card}`} aria-label={t('onboarding.title')}>
      <div className={local.head}>
        <div>
          <h2>{t('onboarding.title')}</h2>
          <p className={styles.panelSub}>{t('onboarding.progress', { done, total: steps.length })}</p>
        </div>
        <button
          type="button"
          className={local.dismiss}
          onClick={() => {
            setDismissed(true)
            try {
              localStorage.setItem(dismissKey(session.user.id), '1')
            } catch {
              // storage blocked: hidden for this visit only
            }
          }}
        >
          {t('onboarding.dismiss')}
        </button>
      </div>
      <div className={styles.track} role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={steps.length}>
        <span className={styles.fill} style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className={local.steps}>
        {steps.map((s) => (
          <li key={s.id} className={s.done ? local.done : ''}>
            <span className={local.mark} aria-hidden="true">{s.done ? '✓' : ''}</span>
            {s.done ? <span>{t(`onboarding.${s.id}`)}</span> : <Link to={s.to} className="link-wipe">{t(`onboarding.${s.id}`)}</Link>}
          </li>
        ))}
      </ol>
    </section>
  )
}
