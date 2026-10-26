import { Link } from 'react-router-dom'
import { CONTACT_EMAIL, REPO_URL } from '../lib/site'
import LogoMark from './LogoMark'
import styles from './public.module.css'


const COLUMNS: { title: string; links: { label: string; to: string; external?: boolean }[] }[] = [
  {
    title: 'Product',
    links: [
      { label: 'The loop', to: '/#loop' },
      { label: 'Why it’s different', to: '/#why' },
      { label: 'Pricing', to: '/#pricing' },
      { label: 'FAQ', to: '/#faq' },
    ],
  },
  {
    title: 'Company',
    links: [
      { label: 'Docs', to: '/docs' },
      { label: 'Status', to: '/status' },
      { label: 'About', to: '/about' },
      { label: 'Contact', to: '/contact' },
      { label: 'Source on GitHub', to: REPO_URL, external: true },
      { label: 'Email us', to: `mailto:${CONTACT_EMAIL}`, external: true },
    ],
  },
  {
    title: 'Legal',
    links: [
      { label: 'Privacy', to: '/privacy' },
      { label: 'Terms', to: '/terms' },
    ],
  },
]

/** Footer shared by every public page. */
export default function PublicFooter() {
  return (
    <footer className={styles.footer}>
      <div className={styles.wrap}>
        <div className={styles.footerTop}>
          <div className={styles.footerBrand}>
            <Link to="/" className={styles.logo}>
              <LogoMark />
              CampaignIQ
            </Link>
            <p>
              CampaignIQ turns a single idea into a campaign that improves itself. It scores demand, writes and
              launches the creative, and learns from every round of real engagement, with you approving each step
              that matters.
            </p>
          </div>
          {COLUMNS.map((col) => (
            <div className={styles.footerCol} key={col.title}>
              <h4>{col.title}</h4>
              {col.links.map((l) =>
                l.external ? (
                  <a
                    key={l.label}
                    className="link-wipe"
                    href={l.to}
                    {...(l.to.startsWith('http') ? { target: '_blank', rel: 'noopener noreferrer' } : {})}
                  >
                    {l.label}
                  </a>
                ) : (
                  <Link key={l.label} className="link-wipe" to={l.to}>
                    {l.label}
                  </Link>
                ),
              )}
            </div>
          ))}
        </div>
        <div className={styles.wordmark} aria-hidden="true">
          CampaignIQ
        </div>
        <div className={styles.footerBottom}>
          <span>© 2026 CampaignIQ. All rights reserved. · v{__APP_VERSION__}</span>
        </div>
      </div>
    </footer>
  )
}
