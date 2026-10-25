import { useEffect, useRef, useState } from 'react'
import { supabase } from './supabaseClient'

const POLL_MS = 4000
const GIVE_UP_MS = 6 * 60 * 1000

/**
 * A job on the worker (a "capability run", e.g. applying a crash-test revision):
 * start() dispatches it, then this polls its status until it completes, fails
 * or takes too long. Returns [busy, start].
 */
export function useWorkerRun(onFinish: (ok: boolean, error?: string | null) => void) {
  const [runId, setRunId] = useState<string | null>(null)
  const started = useRef(0)
  const finish = useRef(onFinish)
  finish.current = onFinish

  useEffect(() => {
    if (!runId) return
    const timer = window.setInterval(async () => {
      const { data } = await supabase.from('capability_runs').select('status,error').eq('id', runId).maybeSingle()
      const row = data as { status?: string; error?: string | null } | null
      if (row?.status === 'completed' || row?.status === 'failed' || Date.now() - started.current > GIVE_UP_MS) {
        window.clearInterval(timer)
        setRunId(null)
        finish.current(row?.status === 'completed', row?.error)
      }
    }, POLL_MS)
    return () => window.clearInterval(timer)
  }, [runId])

  async function start(capability: string, params: Record<string, unknown>): Promise<string | null> {
    const { data, error } = await supabase.functions.invoke('trigger-capability-run', { body: { capability, params } })
    if (error) return error.message
    started.current = Date.now()
    setRunId((data as { run_id: string }).run_id)
    return null
  }

  return [runId !== null, start] as const
}
