import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { supabase } from '../lib/supabaseClient'
import type { Campaign, GateDecision, Iteration, Persona } from '../lib/types'

const GATE_NUMBER_BY_STATUS: Partial<Record<string, 1 | 2>> = {
  awaiting_gate_1: 1,
  awaiting_gate_2: 2,
}

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [personas, setPersonas] = useState<Persona[]>([])
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [pendingGate, setPendingGate] = useState<GateDecision | null>(null)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)

  async function load() {
    if (!id) return
    const [{ data: campaignData }, { data: personaData }, { data: iterationData }] = await Promise.all([
      supabase.from('campaigns').select('*').eq('id', id).single(),
      supabase.from('personas').select('*').eq('campaign_id', id),
      supabase.from('iterations').select('*').eq('campaign_id', id).order('round_number'),
    ])

    setCampaign(campaignData as Campaign)
    setPersonas((personaData as Persona[]) ?? [])
    setIterations((iterationData as Iteration[]) ?? [])

    const gateNumber = campaignData ? GATE_NUMBER_BY_STATUS[campaignData.status] : undefined
    if (gateNumber && campaignData) {
      const { data: gateData } = await supabase
        .from('gate_decisions')
        .select('*')
        .eq('campaign_id', id)
        .eq('gate_number', gateNumber)
        .eq('round_number', campaignData.current_round)
        .maybeSingle()
      setPendingGate((gateData as GateDecision) ?? null)
    } else {
      setPendingGate(null)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  async function submitDecision(decision: 'approve' | 'edit' | 'reject') {
    if (!pendingGate) return
    setSubmitting(true)
    await supabase
      .from('gate_decisions')
      .update({ decision, comment: comment || null, decided_at: new Date().toISOString() })
      .eq('id', pendingGate.id)
    setSubmitting(false)
    setComment('')
    await load()
  }

  async function setPrimaryPersona(personaId: string) {
    if (!id) return
    await supabase.from('personas').update({ is_primary: false }).eq('campaign_id', id)
    await supabase.from('personas').update({ is_primary: true }).eq('id', personaId)
    await load()
  }

  if (!campaign) return <p className="p-8 text-gray-500">Loading…</p>

  return (
    <div className="max-w-3xl mx-auto p-8 space-y-8">
      <Link to="/" className="text-sm text-gray-500 hover:underline">
        &larr; All campaigns
      </Link>

      <div>
        <h1 className="text-2xl font-semibold">{campaign.idea}</h1>
        <p className="text-sm text-gray-500 mt-1">
          {campaign.domain_category} · status <span className="font-mono">{campaign.status}</span> · round{' '}
          {campaign.current_round}
        </p>
      </div>

      <section>
        <h2 className="text-lg font-medium mb-2">Feasibility</h2>
        <p className="text-sm">
          Score: <strong>{campaign.feasibility_score ?? '—'}</strong>
        </p>
        <p className="text-sm text-gray-600 mt-1">{campaign.feasibility_rationale}</p>
      </section>

      <section>
        <h2 className="text-lg font-medium mb-2">Personas</h2>
        <ul className="space-y-2">
          {personas.map((p) => (
            <li
              key={p.id}
              className={`border rounded-lg p-3 ${p.is_primary ? 'border-purple-400 bg-purple-50' : ''}`}
            >
              <div className="flex justify-between items-center">
                <span className="font-medium">
                  {p.name}
                  {p.is_primary && <span className="ml-2 text-xs text-purple-600">PRIMARY</span>}
                </span>
                {!p.is_primary && (
                  <button onClick={() => setPrimaryPersona(p.id)} className="text-xs text-purple-600 hover:underline">
                    Make primary
                  </button>
                )}
              </div>
              <p className="text-sm text-gray-600">
                {p.demographics} · {p.psychographics}
              </p>
              <p className="text-sm text-gray-600">
                Channel: {p.channel_fit} · Angle: {p.messaging_angle}
              </p>
            </li>
          ))}
        </ul>
      </section>

      {iterations.length > 0 && (
        <section>
          <h2 className="text-lg font-medium mb-2">Creative</h2>
          {iterations.map((it) => (
            <div key={it.id} className="border rounded-lg p-3 mb-2">
              <p className="text-sm text-gray-500">
                Round {it.round_number} · preflight attempt {it.preflight_attempt}
              </p>
              <p className="mt-1">{it.copy_text}</p>
              <p className="text-sm text-gray-600 mt-1">Image: {it.image_prompt}</p>
              <p className="text-sm mt-1">
                Preflight: {it.preflight_score ?? '—'}/100 {it.preflight_passed ? '✅' : '❌'}
              </p>
              {(it.bluesky_post_uri || it.reddit_post_url || it.email_id) && (
                <div className="text-sm text-gray-600 mt-1 space-x-3">
                  {it.bluesky_post_uri && <span>Bluesky ✅</span>}
                  {it.reddit_post_url && <span>Reddit ✅</span>}
                  {it.email_id && <span>Email ✅</span>}
                </div>
              )}
            </div>
          ))}
        </section>
      )}

      {pendingGate && !pendingGate.decided_at && (
        <section className="border-t pt-6">
          <h2 className="text-lg font-medium mb-2">Gate {pendingGate.gate_number} decision needed</h2>
          <textarea
            className="w-full border rounded-lg p-2 text-sm"
            placeholder="Optional comment…"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex gap-2 mt-3">
            <button
              disabled={submitting}
              onClick={() => submitDecision('approve')}
              className="px-4 py-2 rounded-lg bg-green-600 text-white text-sm disabled:opacity-50"
            >
              Approve
            </button>
            <button
              disabled={submitting}
              onClick={() => submitDecision('edit')}
              className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm disabled:opacity-50"
            >
              Approve with edits
            </button>
            <button
              disabled={submitting}
              onClick={() => submitDecision('reject')}
              className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm disabled:opacity-50"
            >
              Reject
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            "Approve with edits": change something above first (e.g. set a different primary persona),
            then click this to record the decision as an edit.
          </p>
        </section>
      )}
    </div>
  )
}
