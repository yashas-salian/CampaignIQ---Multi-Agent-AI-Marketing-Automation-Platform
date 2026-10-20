import { Link, useLocation } from 'react-router-dom'
import PublicLayout from '../components/PublicLayout'
import { ArrowIcon } from '../components/PublicNav'
import { useAuthTargets } from '../lib/site'
import styles from '../components/public.module.css'
import local from './NotFound.module.css'

export default function NotFound() {
  const { pathname } = useLocation()
  const { authed } = useAuthTargets()
  return (
    <PublicLayout>
      <section className={`${local.wrap} ${styles.enter}`}>
        <div className={local.code} aria-hidden="true">
          4<span>0</span>4
        </div>
        <h1 className={local.title}>This page took a different route.</h1>
        <p className={styles.lead}>
          Nothing lives at <code className={local.path}>{pathname}</code>. It may have moved, or the link was mistyped.
        </p>
        <div className={styles.ctaRow}>
          <Link className={`${styles.btn} ${styles.btnPrimary}`} to={authed ? '/dashboard' : '/'}>
            {authed ? 'Back to dashboard' : 'Back to home'}
            <ArrowIcon className={styles.arrow} />
          </Link>
          <Link className={`${styles.btn} ${styles.btnGhost}`} to="/contact">
            Report a broken link
          </Link>
        </div>
      </section>
    </PublicLayout>
  )
}
