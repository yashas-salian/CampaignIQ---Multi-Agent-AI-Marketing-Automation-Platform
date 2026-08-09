import { useEffect, useState } from 'react'
import { supabase } from '../lib/supabaseClient'

const CAPABILITIES = ['llm', 'image', 'judge'] as const

interface MaskedKey {
  capability: string
  masked_key: string
  updated_at: string
}

export default function Settings() {
  const [keys, setKeys] = useState<Record<string, MaskedKey>>({})
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  async function load() {
    const { data } = await supabase.from('provider_keys_masked').select('*')
    const byCapability: Record<string, MaskedKey> = {}
    for (const row of (data as MaskedKey[]) ?? []) {
      byCapability[row.capability] = row
    }
    setKeys(byCapability)
  }

  useEffect(() => {
    load()
  }, [])

  async function submit(capability: string) {
    const apiKey = inputs[capability]
    if (!apiKey) return
    setSubmitting(capability)
    setMessage(null)

    const { data, error } = await supabase.functions.invoke('submit-provider-key', {
      body: { capability, api_key: apiKey },
    })

    setSubmitting(null)
    if (error) {
      setMessage(`Failed: ${error.message}`)
      return
    }
    setMessage(`Saved ${capability} key (${data.masked_key})`)
    setInputs((prev) => ({ ...prev, [capability]: '' }))
    await load()
  }

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <h1 className="text-2xl font-semibold">Settings — Bring Your Own Key</h1>
      <p className="text-sm text-gray-500">
        Plug in your own paid API key per capability to get paid-tier quality without a subscription.
        Keys are encrypted server-side; only the last 4 characters are ever shown here.
      </p>

      {message && <p className="text-sm text-purple-600">{message}</p>}

      {CAPABILITIES.map((capability) => (
        <div key={capability} className="border rounded-lg p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="font-medium capitalize">{capability}</span>
            <span className="text-sm text-gray-500 font-mono">{keys[capability]?.masked_key ?? 'not set'}</span>
          </div>
          <div className="flex gap-2">
            <input
              type="password"
              placeholder="sk-..."
              value={inputs[capability] ?? ''}
              onChange={(e) => setInputs((prev) => ({ ...prev, [capability]: e.target.value }))}
              className="flex-1 border rounded-lg p-2 text-sm"
            />
            <button
              onClick={() => submit(capability)}
              disabled={submitting === capability}
              className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm disabled:opacity-50"
            >
              {submitting === capability ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ))}
    </div>
  )
}
