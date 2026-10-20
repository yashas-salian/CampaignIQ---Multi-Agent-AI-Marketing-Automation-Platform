import type { ReactNode } from 'react'
import PublicFooter from './PublicFooter'
import PublicNav from './PublicNav'
import styles from './public.module.css'

/** Navbar + content + footer, for every public page except Landing (which has its own hero layout). */
export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <PublicNav />
      <main className={styles.main}>
        <div className={styles.wrap}>{children}</div>
      </main>
      <PublicFooter />
    </div>
  )
}
