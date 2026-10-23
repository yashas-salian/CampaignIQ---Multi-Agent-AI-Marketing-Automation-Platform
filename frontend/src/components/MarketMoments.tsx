import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import css from './MarketMoments.module.css'

export interface MarketAlert {
  id: number
  campaign_id: string
  kind: 'trend' | 'news'
  detail: { keyword: string; value: number; baseline: number; ratio: number | null; headline?: string | null }
  created_at: string
  campaigns?: { idea: string } | null
}

/** "Your topic just got hot": search interest or news coverage spiked for a live campaign. */
export default function MarketMoments({
  alerts,
  onDismiss,
  showCampaign = false,
}: {
  alerts: MarketAlert[]
  onDismiss: (id: number) => void
  showCampaign?: boolean
}) {
  const { t, i18n } = useTranslation()
  if (!alerts.length) return null
  const when = new Intl.RelativeTimeFormat(i18n.language, { numeric: 'auto' })
  const ago = (iso: string) => {
    const hours = Math.round((new Date(iso).getTime() - Date.now()) / 3600000)
    return Math.abs(hours) < 24 ? when.format(hours, 'hour') : when.format(Math.round(hours / 24), 'day')
  }
  return (
    <section className={css.moments} aria-label={t('market.title')}>
      {alerts.map((a) => (
        <article key={a.id} className={css.moment}>
          <span className={css.icon} aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none">
              {a.kind === 'trend' ? (
                <path d="M3 17l6-6 4 4 8-8M15 7h6v6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              ) : (
                <path d="M5 4h11v16H6a1 1 0 0 1-1-1zM16 8h3v11a1 1 0 0 1-2 0M8 8h5M8 12h5M8 16h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              )}
            </svg>
          </span>
          <div className={css.body}>
            <strong>
              {a.kind === 'trend'
                ? t('market.trend', { keyword: a.detail.keyword, ratio: a.detail.ratio ?? '—' })
                : t('market.news', { keyword: a.detail.keyword, count: a.detail.value })}
            </strong>
            <p>
              {a.kind === 'trend'
                ? t('market.trendDetail', { value: a.detail.value, baseline: a.detail.baseline })
                : t('market.newsDetail', { baseline: a.detail.baseline })}
              {a.detail.headline ? <> · <q>{a.detail.headline}</q></> : null}
            </p>
            <span className={css.meta}>
              {ago(a.created_at)} · {t('market.hint')}
              {showCampaign && a.campaigns?.idea && (
                <>
                  {' · '}
                  <Link to={`/campaigns/${a.campaign_id}`} className="link-wipe">
                    {a.campaigns.idea.length > 48 ? `${a.campaigns.idea.slice(0, 48)}…` : a.campaigns.idea}
                  </Link>
                </>
              )}
            </span>
          </div>
          <button type="button" className={css.dismiss} onClick={() => onDismiss(a.id)} aria-label={t('market.dismiss')}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </article>
      ))}
    </section>
  )
}
