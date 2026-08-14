import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { supabase } from '../lib/supabaseClient'
import type { Campaign } from '../lib/types'

export default function Dashboard() {
  const { t } = useTranslation()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)

  const [idea, setIdea] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('en')
  const [creating, setCreating] = useState(false)
  const [createMessage, setCreateMessage] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    const { data } = await supabase.from('campaigns').select('*').order('created_at', { ascending: false })
    setCampaigns((data as Campaign[]) ?? [])
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  async function createCampaign() {
    if (!idea.trim()) return
    setCreating(true)
    setCreateMessage(null)

    const { error } = await supabase.functions.invoke('create-campaign', {
      body: { idea, target_language: targetLanguage },
    })

    setCreating(false)
    if (error) {
      setCreateMessage(`Failed to dispatch: ${error.message}`)
      return
    }
    setCreateMessage('Campaign creation started — it will appear below once feasibility scoring completes.')
    setIdea('')
  }

  return (
    <div className="max-w-3xl mx-auto p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">{t('dashboard.title')}</h1>
        <button onClick={load} className="text-sm text-gray-500 hover:underline">
          {t('dashboard.refresh')}
        </button>
      </div>

      <div className="border rounded-lg p-4 mb-6 space-y-3">
        <h2 className="font-medium">{t('dashboard.createTitle')}</h2>
        <textarea
          placeholder={t('dashboard.ideaPlaceholder')}
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={2}
          className="w-full border rounded-lg p-2 text-sm"
        />
        <div className="flex gap-2 items-center">
          <label className="text-sm text-gray-500">{t('dashboard.languageLabel')}</label>
          <select
            value={targetLanguage}
            onChange={(e) => setTargetLanguage(e.target.value)}
            className="border rounded-lg p-1.5 text-sm"
          >
            {CAMPAIGN_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <button
            onClick={createCampaign}
            disabled={creating || !idea.trim()}
            className="ml-auto px-4 py-1.5 rounded-lg bg-purple-600 text-white text-sm disabled:opacity-50"
          >
            {creating ? t('dashboard.creating') : t('dashboard.createSubmit')}
          </button>
        </div>
        {createMessage && <p className="text-sm text-purple-600">{createMessage}</p>}
      </div>

      {loading && <p className="text-gray-500">{t('common.loading')}</p>}

      {!loading && campaigns.length === 0 && <p className="text-gray-500">{t('dashboard.empty')}</p>}

      <ul className="space-y-3">
        {campaigns.map((c) => (
          <li key={c.id} className="border rounded-lg p-4 hover:bg-gray-50">
            <Link to={`/campaigns/${c.id}`} className="block">
              <div className="flex justify-between items-center">
                <span className="font-medium">{c.idea}</span>
                <span className="text-xs uppercase tracking-wide text-gray-500">{c.status}</span>
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {c.domain_category} · {t('dashboard.feasibility')} {c.feasibility_score ?? '—'}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
