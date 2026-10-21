import type { CSSProperties } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { supabase } from '../lib/supabaseClient'
import type { Campaign, CampaignStatus, GateDecision, Iteration, Persona } from '../lib/types'
import styles from '../styles/app.module.css'
import local from './CampaignDetail.module.css'

const GATE_NUMBER_BY_STATUS: Partial<Record<CampaignStatus, 1 | 2>> = {
  awaiting_gate_1: 1,
  awaiting_gate_2: 2,
}

// Must match DomainCategory in src/capabilities/idea_intake.py (and the check in schema_m7.sql).
const DOMAINS = [
  'fitness_wellness', 'b2b_saas', 'ecommerce_retail', 'food_beverage', 'finance_fintech', 'education',
  'consumer_electronics', 'travel_hospitality', 'real_estate', 'healthcare', 'entertainment_media', 'other',
] as const

const STEPS = ['s_intake', 's_feasibility', 's_audience', 's_gate1', 's_creative', 's_preflight', 's_gate2', 's_distribute', 's_measure'] as const

/** Index of the step the campaign is on now (STEPS.length = all done). */
function currentStep(status: CampaignStatus): number {
  switch (status) {
    case 'created':
      return 1
    case 'awaiting_gate_1':
      return 3
    case 'awaiting_next_round':
      return 4
    case 'awaiting_gate_2':
      return 6
    case 'awaiting_metrics':
      return 8
    case 'completed':
      return STEPS.length
    case 'rejected':
      return -1
  }
}

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/** at://did/app.bsky.feed.post/rkey → public bsky.app URL. */
function blueskyUrl(uri: string) {
  const m = uri.match(/^at:\/\/([^/]+)\/app\.bsky\.feed\.post\/([^/]+)$/)
  return m ? `https://bsky.app/profile/${m[1]}/post/${m[2]}` : null
}

/** Deterministic seed per round, so a round always previews the same picture. */
function seedOf(id: string) {
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h % 1_000_000
}

/**
 * The posted image isn't stored (only its prompt is), so this regenerates a
 * preview from the round's own prompt via Pollinations, the same free service
 * the backend uses (src/tools/image_gen.py). Falls back to a placeholder.
 */
function RoundImage({ prompt, seedFrom }: { prompt: string | null; seedFrom: string }) {
  const { t } = useTranslation()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(prompt ? 'loading' : 'error')
  const src = prompt
    ? `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt)}?width=512&height=512&nologo=true&seed=${seedOf(seedFrom)}`
    : ''
  if (state === 'error') {
    return (
      <div className={`${styles.placeholder} ${local.creativeImg}`}>
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.5" />
          <path d="M3 15l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
        <span className={styles.placeholderLabel}>{t('cd.imagePlaceholder')}</span>
      </div>
    )
  }
  return (
    <figure className={`${local.creativeImg} ${local.preview} ${state === 'ready' ? local.previewReady : ''}`}>
      {state === 'loading' && <span className={`${styles.skeleton} ${local.previewSkeleton}`} aria-hidden="true" />}
      <img src={src} alt={prompt ?? ''} loading="lazy" decoding="async" onLoad={() => setState('ready')} onError={() => setState('error')} />
      <figcaption>{t('cd.previewNote')}</figcaption>
    </figure>
  )
}

function StatusPill({ status }: { status: CampaignStatus }) {
  const { t } = useTranslation()
  const tone =
    status === 'awaiting_gate_1' || status === 'awaiting_gate_2'
      ? styles.pillAction
      : status === 'completed'
        ? styles.pillDone
        : status === 'rejected'
          ? styles.pillRejected
          : styles.pillRunning
  return (
    <span className={`${styles.pill} ${tone}`}>
      <span className={styles.pillDot} aria-hidden="true" />
      {t(`dash.st_${status}`)}
    </span>
  )
}

/** Feasibility as a ring; the number stays in text ink. */
function ScoreRing({ score }: { score: number | null }) {
  const { t } = useTranslation()
  const r = 52
  const c = 2 * Math.PI * r
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  return (
    <div className={local.ring}>
      <svg viewBox="0 0 128 128" aria-hidden="true">
        <circle cx="64" cy="64" r={r} className={local.ringTrack} />
        <circle
          cx="64"
          cy="64"
          r={r}
          className={local.ringFill}
          style={{ strokeDasharray: c, '--offset': c * (1 - pct) } as CSSProperties}
        />
      </svg>
      <div className={local.ringLabel}>
        <strong>{score ?? '—'}</strong>
        <span>{t('cd.outOf')}</span>
      </div>
    </div>
  )
}

export default function CampaignDetail() {
  const { t, i18n } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [missing, setMissing] = useState(false)
  const [personas, setPersonas] = useState<Persona[]>([])
  const [iterations, setIterations] = useState<Iteration[]>([])
  const [pendingGate, setPendingGate] = useState<GateDecision | null>(null)
  const [comment, setComment] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [confirm, setConfirm] = useState<'reject' | 'stop' | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [category, setCategory] = useState('')

  const load = useCallback(async () => {
    if (!id) return
    const [{ data: campaignData }, { data: personaData }, { data: iterationData }] = await Promise.all([
      supabase.from('campaigns').select('*').eq('id', id).maybeSingle(),
      supabase.from('personas').select('*').eq('campaign_id', id),
      supabase.from('iterations').select('*').eq('campaign_id', id).order('round_number').order('preflight_attempt'),
    ])
    if (!campaignData) {
      setMissing(true)
      return
    }
    setCampaign(campaignData as Campaign)
    setPersonas(((personaData as Persona[]) ?? []).sort((a, b) => Number(b.is_primary) - Number(a.is_primary)))
    setIterations((iterationData as Iteration[]) ?? [])

    const gateNumber = GATE_NUMBER_BY_STATUS[(campaignData as Campaign).status]
    if (gateNumber) {
      const { data: gateData } = await supabase
        .from('gate_decisions')
        .select('*')
        .eq('campaign_id', id)
        .eq('gate_number', gateNumber)
        .eq('round_number', (campaignData as Campaign).current_round)
        .maybeSingle()
      setPendingGate((gateData as GateDecision) ?? null)
    } else {
      setPendingGate(null)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  // Live: the background worker writes status, personas and rounds as it goes.
  useEffect(() => {
    if (!id) return
    const channel = supabase
      .channel(`campaign-${id}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaigns', filter: `id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'iterations', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'personas', filter: `campaign_id=eq.${id}` }, () => load())
      .on('postgres_changes', { event: '*', schema: 'public', table: 'gate_decisions', filter: `campaign_id=eq.${id}` }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [id, load])

  // A destructive button needs a second click within 3s.
  useEffect(() => {
    if (!confirm) return
    const timer = setTimeout(() => setConfirm(null), 3000)
    return () => clearTimeout(timer)
  }, [confirm])

  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(null), 6000)
    return () => clearTimeout(timer)
  }, [notice])

  async function resumeNow() {
    // Best-effort: the scheduled sweep is the reliability backstop if this fails.
    try {
      await supabase.functions.invoke('resume-campaign', { body: { campaign_id: id } })
    } catch {
      // no-op: cron will pick it up
    }
  }

  async function submitDecision(decision: 'approve' | 'edit' | 'reject') {
    if (!pendingGate) return
    if (decision === 'reject' && confirm !== 'reject') {
      setConfirm('reject')
      return
    }
    setConfirm(null)
    setSubmitting(true)
    // Gate 1 category correction: update the campaign (the graph re-reads it after
    // the gate, so the bandit uses it) and record a human-verified label for retraining.
    const predicted = campaign?.domain_category
    const corrected = pendingGate.gate_number === 1 && decision !== 'reject' && category && predicted && category !== predicted
    if (corrected && campaign) {
      await supabase.from('campaigns').update({ domain_category: category }).eq('id', campaign.id)
      const { error: correctionError } = await supabase.from('domain_corrections').insert({
        campaign_id: campaign.id,
        idea: campaign.idea,
        predicted_domain: predicted,
        corrected_domain: category,
      })
      // Never block the gate on the training log (e.g. schema_m7.sql not applied yet).
      if (correctionError) console.warn('domain correction not recorded:', correctionError.message)
      if (decision === 'approve') decision = 'edit'
    }
    await supabase
      .from('gate_decisions')
      .update({ decision, comment: comment || null, decided_at: new Date().toISOString() })
      .eq('id', pendingGate.id)
    await resumeNow()
    setSubmitting(false)
    setComment('')
    setNotice(t('cd.decisionSent'))
    await load()
  }

  async function stopCampaign() {
    if (!id) return
    if (confirm !== 'stop') {
      setConfirm('stop')
      return
    }
    setConfirm(null)
    setStopping(true)
    await supabase.from('campaigns').update({ stop_requested: true }).eq('id', id)
    await resumeNow()
    setStopping(false)
    await load()
  }

  async function setPrimaryPersona(personaId: string) {
    if (!id) return
    // Optimistic: reorder immediately, then persist.
    setPersonas((prev) =>
      prev.map((p) => ({ ...p, is_primary: p.id === personaId })).sort((a, b) => Number(b.is_primary) - Number(a.is_primary)),
    )
    await supabase.from('personas').update({ is_primary: false }).eq('campaign_id', id)
    await supabase.from('personas').update({ is_primary: true }).eq('id', personaId)
    await load()
  }

  // Latest attempt per round only (earlier pre-flight retries are history).
  const rounds = useMemo(() => {
    const byRound = new Map<number, Iteration>()
    for (const it of iterations) byRound.set(it.round_number, it)
    return [...byRound.values()].sort((a, b) => b.round_number - a.round_number)
  }, [iterations])

  if (missing) {
    return (
      <div className={styles.page}>
        <div className={`${styles.panel} ${styles.empty}`}>
          <h3>{t('cd.notFound')}</h3>
          <Link to="/dashboard" className={`${styles.btn} ${styles.primary}`}>
            {t('cd.back')}
          </Link>
        </div>
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className={styles.page}>
        <span className={styles.skeleton} style={{ height: 16, width: 140 }} />
        <span className={styles.skeleton} style={{ height: 40, width: '60%' }} />
        <span className={styles.skeleton} style={{ height: 88 }} />
        <div className={styles.grid2}>
          <span className={styles.skeleton} style={{ height: 260 }} />
          <span className={styles.skeleton} style={{ height: 260 }} />
        </div>
      </div>
    )
  }

  const isActive = !['completed', 'rejected'].includes(campaign.status)
  const step = currentStep(campaign.status)
  const lang = CAMPAIGN_LANGUAGES.find((l) => l.code === campaign.target_language)
  const gateOpen = pendingGate && !pendingGate.decided_at
  const created = new Date(campaign.created_at).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' })
  const summaryEntries = campaign.campaign_summary
    ? Object.entries(campaign.campaign_summary).filter(([, v]) => ['string', 'number', 'boolean'].includes(typeof v))
    : []

  return (
    <div className={styles.page}>
      <div className={`${styles.crumbs} ${styles.enter}`}>
        <Link to="/dashboard" className={`${styles.back} link-wipe`}>
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M19 12H5M11 18l-6-6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {t('cd.back')}
        </Link>
        <span className={local.live}>
          {t('dash.live')}
        </span>
      </div>

      <header className={`${styles.header} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
        <div>
          <span className={styles.eyebrow}>{humanize(campaign.domain_category)}</span>
          <h1 className={styles.title}>{campaign.idea}</h1>
          <div className={styles.meta}>
            <StatusPill status={campaign.status} />
            <span className={styles.metaChip}>
              {campaign.max_rounds
                ? t('campaignDetail.roundOf', { current: campaign.current_round, max: campaign.max_rounds })
                : t('campaignDetail.round', { current: campaign.current_round })}
            </span>
            {lang && <span className={styles.metaChip}>{lang.label}</span>}
            <span className={styles.metaChip}>{t('cd.created', { time: created })}</span>
          </div>
        </div>
        <div className={styles.headerActions}>
          <Link to={`/campaigns/${id}/metrics`} className={`${styles.btn} ${styles.ghost}`}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 19V5M4 19h16M8 15l4-4 3 3 5-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {t('cd.metrics')}
          </Link>
          {isActive && (
            <button
              type="button"
              onClick={stopCampaign}
              disabled={stopping || campaign.stop_requested}
              className={`${styles.btn} ${confirm === 'stop' ? styles.dangerSolid : styles.danger}`}
            >
              {campaign.stop_requested || stopping ? t('cd.stopping') : confirm === 'stop' ? t('cd.stopConfirm') : t('cd.stop')}
            </button>
          )}
        </div>
      </header>

      {notice && (
        <p className={`${styles.toast} ${styles.toastOk}`} role="status">
          {notice}
        </p>
      )}

      {gateOpen && (
        <section className={`${styles.panel} ${local.gate} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties} aria-live="polite">
          <div className={local.gateHead}>
            <span className={local.gateBadge}>{pendingGate.gate_number}</span>
            <div>
              <h2>{t('campaignDetail.gateTitle', { number: pendingGate.gate_number })}</h2>
              <p className={styles.panelSub}>{pendingGate.gate_number === 1 ? t('cd.gate1Body') : t('cd.gate2Body')}</p>
            </div>
          </div>
          {pendingGate.gate_number === 1 && (
            <label className={styles.field}>
              <span>{t('cd.categoryLabel')}</span>
              <select
                className={`${styles.select} ${local.categorySelect}`}
                value={category || campaign.domain_category}
                onChange={(e) => setCategory(e.target.value)}
              >
                {DOMAINS.map((d) => (
                  <option key={d} value={d}>
                    {humanize(d)}
                    {d === campaign.domain_category ? ' ✓' : ''}
                  </option>
                ))}
              </select>
              <small className={local.hint}>{t('cd.categoryHint')}</small>
            </label>
          )}
          <label className={styles.field}>
            <span>{t('cd.commentLabel')}</span>
            <textarea
              className={styles.textarea}
              rows={2}
              placeholder={t('campaignDetail.commentPlaceholder')}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </label>
          <div className={local.gateActions}>
            <button type="button" disabled={submitting} onClick={() => submitDecision('approve')} className={`${styles.btn} ${styles.primary}`}>
              {submitting && <span className={styles.spinner} aria-hidden="true" />}
              {t('campaignDetail.approve')}
            </button>
            <button type="button" disabled={submitting} onClick={() => submitDecision('edit')} className={`${styles.btn} ${styles.ghost}`}>
              {t('campaignDetail.approveEdits')}
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={() => submitDecision('reject')}
              className={`${styles.btn} ${confirm === 'reject' ? styles.dangerSolid : styles.danger}`}
            >
              {confirm === 'reject' ? t('cd.rejectConfirm') : t('campaignDetail.reject')}
            </button>
          </div>
          <p className={local.hint}>{t('campaignDetail.editHint')}</p>
        </section>
      )}

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('cd.progressTitle')}</h2>
        </div>
        <ol className={`${local.stepper} ${campaign.status === 'rejected' ? local.stepperRejected : ''}`}>
          {STEPS.map((s, i) => {
            const state = step === -1 ? '' : i < step ? local.done : i === step ? local.current : ''
            return (
              <li key={s} className={state} style={{ '--i': i } as CSSProperties}>
                <span className={local.stepDot} aria-hidden="true">
                  {i < step ? (
                    <svg viewBox="0 0 24 24" fill="none">
                      <path d="M5 13l4 4L19 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : (
                    i + 1
                  )}
                </span>
                <span className={local.stepLabel}>{t(`cd.${s}`)}</span>
              </li>
            )
          })}
        </ol>
      </section>

      <div className={styles.grid2}>
        <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('campaignDetail.personasTitle')}</h2>
            <span className={styles.chip}>{personas.length}</span>
          </div>
          {personas.length === 0 ? (
            <p className={styles.muted}>{t('cd.noPersonas')}</p>
          ) : (
            <div className={local.personas}>
              {personas.map((p) => (
                <article key={p.id} className={`${local.persona} ${p.is_primary ? local.personaPrimary : ''}`}>
                  <div className={local.personaHead}>
                    <span className={local.avatar} aria-hidden="true">
                      {p.name
                        .split(/\s+/)
                        .slice(0, 2)
                        .map((w) => w[0])
                        .join('')
                        .toUpperCase()}
                    </span>
                    <div className={local.personaName}>
                      <strong>{p.name}</strong>
                      {p.is_primary ? (
                        <span className={local.primaryBadge}>{t('campaignDetail.primaryBadge')}</span>
                      ) : (
                        <button type="button" className={`${local.makePrimary} link-wipe`} onClick={() => setPrimaryPersona(p.id)}>
                          {t('campaignDetail.makePrimary')}
                        </button>
                      )}
                    </div>
                  </div>
                  <p>{p.demographics}</p>
                  <p>{p.psychographics}</p>
                  <dl className={local.personaMeta}>
                    <div>
                      <dt>{t('cd.channel')}</dt>
                      <dd>{p.channel_fit}</dd>
                    </div>
                    <div>
                      <dt>{t('cd.angle')}</dt>
                      <dd>{p.messaging_angle}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('campaignDetail.feasibilityTitle')}</h2>
          </div>
          <ScoreRing score={campaign.feasibility_score} />
          <p className={`${styles.muted} ${local.rationale}`}>{campaign.feasibility_rationale || t('cd.noRationale')}</p>
        </section>
      </div>

      <section className={`${styles.panel} ${styles.enter}`} style={{ '--i': 6 } as CSSProperties}>
        <div className={styles.panelHead}>
          <h2>{t('campaignDetail.roundsTitle')}</h2>
        </div>
        {rounds.length === 0 ? (
          <p className={styles.muted}>{t('cd.noRounds')}</p>
        ) : (
          <ol className={local.rounds}>
            {rounds.map((it, i) => {
              const bsky = it.bluesky_post_uri ? blueskyUrl(it.bluesky_post_uri) : null
              const published = it.bluesky_post_uri || it.reddit_post_url || it.email_id
              return (
                <li key={it.id} className={local.round} style={{ '--i': i } as CSSProperties}>
                  <div className={local.roundRail}>
                    <span className={local.roundNum}>R{it.round_number}</span>
                  </div>
                  <div className={local.roundBody}>
                    <div className={local.roundTop}>
                      <strong>{t('cd.round', { round: it.round_number })}</strong>
                      <span className={styles.chip}>{t('cd.attempt', { attempt: it.preflight_attempt })}</span>
                      {it.image_style && it.copy_tone && (
                        <span className={styles.chip} title={t('cd.arm')}>
                          {humanize(it.image_style)} × {it.copy_tone.replace(/_/g, ' ')}
                        </span>
                      )}
                    </div>
                    <div className={local.creative}>
                      <RoundImage key={it.id} seedFrom={it.id} prompt={it.image_prompt} />
                      <div className={local.creativeText}>
                        {it.copy_text && <blockquote className={local.copy}>{it.copy_text}</blockquote>}
                        {it.image_prompt && (
                          <p className={local.prompt}>
                            <span>{t('cd.imagePrompt')}</span>
                            {it.image_prompt}
                          </p>
                        )}
                        <div className={local.preflight}>
                          <span>{t('cd.preflight')}</span>
                          <div className={styles.track}>
                            <span className={styles.fill} style={{ width: `${it.preflight_score ?? 0}%` }} />
                          </div>
                          <b>{it.preflight_score ?? '—'}</b>
                          <span className={it.preflight_passed ? local.pass : local.fail}>{it.preflight_passed ? '✓' : '✕'}</span>
                        </div>
                        <div className={local.channels}>
                          <span>{t('cd.publishedTo')}</span>
                          {!published && <em>{t('cd.notPublished')}</em>}
                          {it.bluesky_post_uri &&
                            (bsky ? (
                              <a className={`${styles.chip} ${styles.chipOk}`} href={bsky} target="_blank" rel="noopener noreferrer">
                                Bluesky ↗
                              </a>
                            ) : (
                              <span className={`${styles.chip} ${styles.chipOk}`}>Bluesky</span>
                            ))}
                          {it.reddit_post_url && (
                            <a className={`${styles.chip} ${styles.chipOk}`} href={it.reddit_post_url} target="_blank" rel="noopener noreferrer">
                              Reddit ↗
                            </a>
                          )}
                          {it.email_id && <span className={`${styles.chip} ${styles.chipOk}`}>Email</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                </li>
              )
            })}
          </ol>
        )}
      </section>

      {campaign.status === 'completed' && campaign.campaign_summary && (
        <section className={`${styles.panel} ${local.summary} ${styles.enter}`} style={{ '--i': 7 } as CSSProperties}>
          <div className={styles.panelHead}>
            <h2>{t('campaignDetail.summaryTitle')}</h2>
          </div>
          {summaryEntries.length > 0 && (
            <dl className={local.summaryGrid}>
              {summaryEntries.map(([k, v]) => (
                <div key={k}>
                  <dt>{humanize(k)}</dt>
                  <dd>{typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : String(v)}</dd>
                </div>
              ))}
            </dl>
          )}
          <details className={styles.details}>
            <summary>{t('cd.rawData')}</summary>
            <pre className={styles.code}>{JSON.stringify(campaign.campaign_summary, null, 2)}</pre>
          </details>
        </section>
      )}
    </div>
  )
}
