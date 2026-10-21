import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './UsageStats.module.css'

interface Row {
  day: string
  provider: string
  calls: number
  failures: number
  tokens: number
  p50_ms: number
  p95_ms: number
}

const fmt = new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 })

/** AI calls, failures, tokens and latency for the active organisation (managers). */
export default function UsageStats() {
  const { t } = useTranslation()
  const { active } = useOrg()
  const [rows, setRows] = useState<Row[]>([])

  useEffect(() => {
    if (!active) return
    supabase.rpc('llm_usage_stats', { p_org: active.id, p_days: 14 }).then(({ data }) => setRows((data as Row[] | null) ?? []))
  }, [active])

  const totals = useMemo(() => {
    const calls = rows.reduce((s, r) => s + r.calls, 0)
    const failures = rows.reduce((s, r) => s + r.failures, 0)
    return {
      calls,
      tokens: rows.reduce((s, r) => s + Number(r.tokens), 0),
      failureRate: calls ? Math.round((failures / calls) * 1000) / 10 : 0,
      p95: rows.length ? Math.max(...rows.map((r) => r.p95_ms)) : 0,
    }
  }, [rows])

  if (!rows.length) return <p className={styles.muted}>{t('obs.empty')}</p>

  return (
    <div className={local.wrap}>
      <div className={local.kpis}>
        <div>
          <span>{t('obs.calls')}</span>
          <strong>{fmt.format(totals.calls)}</strong>
        </div>
        <div>
          <span>{t('obs.tokens')}</span>
          <strong>{fmt.format(totals.tokens)}</strong>
        </div>
        <div>
          <span>{t('obs.failureRate')}</span>
          <strong className={totals.failureRate > 5 ? local.bad : ''}>{totals.failureRate}%</strong>
        </div>
        <div>
          <span>{t('obs.worstP95')}</span>
          <strong>{(totals.p95 / 1000).toFixed(1)} s</strong>
        </div>
      </div>
      <div className={local.tableWrap}>
        <table className={local.table}>
          <thead>
            <tr>
              <th>{t('obs.day')}</th>
              <th>{t('obs.provider')}</th>
              <th>{t('obs.calls')}</th>
              <th>{t('obs.failures')}</th>
              <th>{t('obs.tokens')}</th>
              <th>p50</th>
              <th>p95</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.day}-${r.provider}`}>
                <td>{r.day}</td>
                <td>{r.provider}</td>
                <td>{r.calls}</td>
                <td className={r.failures ? local.bad : ''}>{r.failures}</td>
                <td>{fmt.format(Number(r.tokens))}</td>
                <td>{(r.p50_ms / 1000).toFixed(1)} s</td>
                <td>{(r.p95_ms / 1000).toFixed(1)} s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className={local.note}>{t('obs.note')}</p>
    </div>
  )
}
