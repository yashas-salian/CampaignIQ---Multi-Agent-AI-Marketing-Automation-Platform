import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { supabase } from '../lib/supabaseClient'

const CAPABILITIES = ['feasibility', 'personas', 'image'] as const
type Capability = (typeof CAPABILITIES)[number]

export default function Tools() {
  const { t } = useTranslation()
  const [capability, setCapability] = useState<Capability>('feasibility')
  const [idea, setIdea] = useState('')
  const [prompt, setPrompt] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [result, setResult] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!runId) return

    const channel = supabase
      .channel(`capability_run_${runId}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'capability_runs', filter: `id=eq.${runId}` },
        (payload) => {
          const row = payload.new as { status: string; result: unknown; error: string | null }
          setStatus(row.status)
          if (row.status === 'completed') setResult(row.result)
          if (row.status === 'failed') setResult({ error: row.error })
        },
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [runId])

  async function submit() {
    setSubmitting(true)
    setResult(null)
    setStatus('dispatching…')

    const params = capability === 'image' ? { prompt } : { idea }
    const { data, error } = await supabase.functions.invoke('trigger-capability-run', {
      body: { capability, params },
    })

    setSubmitting(false)
    if (error) {
      setStatus(`Failed to dispatch: ${error.message}`)
      return
    }
    setRunId(data.run_id)
    setStatus('pending')
  }

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <h1 className="text-2xl font-semibold">{t('tools.title')}</h1>
      <p className="text-sm text-gray-500">{t('tools.subtitle')}</p>

      <div className="space-y-3">
        <select
          value={capability}
          onChange={(e) => setCapability(e.target.value as Capability)}
          className="border rounded-lg p-2 text-sm"
        >
          {CAPABILITIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>

        {capability === 'image' ? (
          <input
            placeholder={t('tools.imagePromptPlaceholder')}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            className="w-full border rounded-lg p-2 text-sm"
          />
        ) : (
          <input
            placeholder={t('tools.ideaPlaceholder')}
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            className="w-full border rounded-lg p-2 text-sm"
          />
        )}

        <button
          onClick={submit}
          disabled={submitting}
          className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm disabled:opacity-50"
        >
          {submitting ? t('tools.dispatching') : t('tools.run')}
        </button>
      </div>

      {status && <p className="text-sm text-gray-600">{t('tools.status', { status })}</p>}
      {result !== null && (
        <pre className="text-xs bg-gray-50 border rounded-lg p-3 overflow-auto">{JSON.stringify(result, null, 2)}</pre>
      )}
    </div>
  )
}
