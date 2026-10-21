import { useEffect, useState } from 'react'

import PublicLayout from '../components/PublicLayout'
import styles from '../components/public.module.css'
import { supabase } from '../lib/supabaseClient'
import local from './Status.module.css'

interface Component {
  component: string
  ok: boolean
  latency_ms: number | null
  detail: string | null
  checked_at: string
  uptime_24h: number | null
  uptime_7d: number | null
  history: { hour: string; ok: boolean }[]
}

const NAMES: Record<string, string> = {
  website: 'Website',
  database_api: 'Database API',
  authentication: 'Sign-in',
  edge_functions: 'App functions',
  public_api: 'Public API',
}

/** Public status page, fed by the uptime workflow (every 15 minutes). */
export default function Status() {
  const [components, setComponents] = useState<Component[] | null>(null)
  const [checkedAt, setCheckedAt] = useState<string | null>(null)

  useEffect(() => {
    supabase.rpc('status_summary').then(({ data }) => {
      const summary = data as { checked_at: string | null; components: Component[] } | null
      setComponents(summary?.components ?? [])
      setCheckedAt(summary?.checked_at ?? null)
    })
  }, [])

  const down = components?.filter((c) => !c.ok) ?? []
  return (
    <PublicLayout>
      <section className={`${local.wrap} ${styles.enter}`}>
        <span className={styles.eyebrow}>Status</span>
        <h1 className={local.title}>
          {components === null
            ? 'Checking…'
            : components.length === 0
              ? 'No checks recorded yet'
              : down.length
                ? `${down.length} component${down.length > 1 ? 's' : ''} affected`
                : 'All systems operational'}
        </h1>
        {checkedAt && <p className={styles.lead}>Last checked {new Date(checkedAt).toLocaleString()}. Checks run every 15 minutes.</p>}
        <ul className={local.list}>
          {(components ?? []).map((c) => (
            <li key={c.component} className={c.ok ? '' : local.down}>
              <div className={local.row}>
                <span className={local.dot} aria-hidden="true" />
                <strong>{NAMES[c.component] ?? c.component}</strong>
                <span className={local.state}>{c.ok ? 'Operational' : `Down${c.detail ? ` (${c.detail})` : ''}`}</span>
              </div>
              <div className={local.bars} aria-label="Last 48 hours, hourly">
                {c.history.map((h) => (
                  <span key={h.hour} className={h.ok ? local.up : local.bad} title={new Date(h.hour).toLocaleString()} />
                ))}
              </div>
              <div className={local.meta}>
                <span>24 h uptime {c.uptime_24h ?? '—'}%</span>
                <span>7 d uptime {c.uptime_7d ?? '—'}%</span>
                {c.latency_ms !== null && <span>{c.latency_ms} ms</span>}
              </div>
            </li>
          ))}
          {components !== null && components.length === 0 && <li>No checks recorded yet.</li>}
        </ul>
      </section>
    </PublicLayout>
  )
}
