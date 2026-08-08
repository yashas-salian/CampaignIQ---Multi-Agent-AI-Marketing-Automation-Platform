import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import type { Campaign } from '../lib/types'

export default function Dashboard() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)

  async function load() {
    setLoading(true)
    const { data } = await supabase.from('campaigns').select('*').order('created_at', { ascending: false })
    setCampaigns((data as Campaign[]) ?? [])
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="max-w-3xl mx-auto p-8">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-semibold">Campaigns</h1>
        <button onClick={load} className="text-sm text-gray-500 hover:underline">
          Refresh
        </button>
      </div>

      {loading && <p className="text-gray-500">Loading…</p>}

      {!loading && campaigns.length === 0 && (
        <p className="text-gray-500">
          No campaigns yet — trigger one with{' '}
          <code className="bg-gray-100 px-1 rounded">
            python -m src.graph.run_campaign "idea"
          </code>
          .
        </p>
      )}

      <ul className="space-y-3">
        {campaigns.map((c) => (
          <li key={c.id} className="border rounded-lg p-4 hover:bg-gray-50">
            <Link to={`/campaigns/${c.id}`} className="block">
              <div className="flex justify-between items-center">
                <span className="font-medium">{c.idea}</span>
                <span className="text-xs uppercase tracking-wide text-gray-500">{c.status}</span>
              </div>
              <div className="text-sm text-gray-500 mt-1">
                {c.domain_category} · feasibility {c.feasibility_score ?? '—'}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
