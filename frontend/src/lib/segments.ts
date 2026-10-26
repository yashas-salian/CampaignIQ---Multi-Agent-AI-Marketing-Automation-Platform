import { useTranslation } from 'react-i18next'

import type { SegmentFilter } from './types'

/** One line saying what a segment's filter means. */
export function useDescribe() {
  const { t } = useTranslation()
  return (f: SegmentFilter) => {
    const parts: string[] = []
    if (f.tags_any?.length) parts.push(t('seg.d.any', { tags: f.tags_any.join(', ') }))
    if (f.tags_all?.length) parts.push(t('seg.d.all', { tags: f.tags_all.join(', ') }))
    if (f.tags_none?.length) parts.push(t('seg.d.none', { tags: f.tags_none.join(', ') }))
    if (f.purchased_within_days) parts.push(t('seg.d.bought', { n: f.purchased_within_days }))
    if (f.not_purchased_within_days) parts.push(t('seg.d.notBought', { n: f.not_purchased_within_days }))
    if (f.product_any?.length) parts.push(t('seg.d.products', { list: f.product_any.join(', ') }))
    if (f.country_any?.length) parts.push(t('seg.d.countries', { list: f.country_any.join(', ') }))
    if (f.match_campaign_language === false) parts.push(t('seg.d.anyLanguage'))
    return parts.length ? parts.join(' · ') : t('seg.d.everyone')
  }
}
