import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { useOrg } from '../lib/useOrg'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/app.module.css'

/** /invite/:token -- joins the organisation the invitation is for (signed-in users only). */
export default function AcceptInvite() {
  const { token } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { reload, setActive } = useOrg()
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)

  useEffect(() => {
    if (!token || started.current) return
    started.current = true // StrictMode runs effects twice; an invitation is single-use
    supabase.rpc('accept_invitation', { p_token: token }).then(async ({ data, error: err }) => {
      if (err) {
        setError(err.message)
        return
      }
      await reload()
      setActive(data as string)
      navigate('/dashboard', { replace: true })
    })
  }, [token, reload, setActive, navigate])

  return (
    <div className={styles.page}>
      <div className={`${styles.panel} ${styles.empty}`}>
        <h3>{error ? t('org.inviteFailed') : t('org.joining')}</h3>
        {error ? <p>{error}</p> : <span className={styles.spinner} aria-hidden="true" />}
        {error && (
          <Link className={`${styles.btn} ${styles.ghost}`} to="/dashboard">
            {t('common.dashboard')}
          </Link>
        )}
      </div>
    </div>
  )
}
