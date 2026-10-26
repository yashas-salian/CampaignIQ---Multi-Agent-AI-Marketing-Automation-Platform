import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import Select from '../components/Select'
import { DOMAINS } from '../lib/domains'
import { usePageLoading } from '../lib/loading'
import { MEMORY_EVAL } from '../lib/memoryEval'
import { toastFailure, toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import type { BrandMemory as Memory, MemoryType } from '../lib/types'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './BrandMemory.module.css'

const TYPES: MemoryType[] = ['BRAND_PREFERENCE', 'POLICY_DECISION', 'CAMPAIGN_LESSON', 'AUDIENCE_INSIGHT', 'FAILED_EXPERIMENT']
const CHANNELS = ['email', 'bluesky', 'mastodon', 'reddit']
const AGES = ['18-24', '25-34', '35-44', '45-54', '55+']
const TONES = ['direct_factual', 'urgency_scarcity', 'humorous', 'aspirational_emotional']
const list = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const pct = (x: number) => `${Math.round(x * 100)}%`
const short = (s: string) => (s.length > 60 ? `${s.slice(0, 57).trimEnd()}…` : s)

function Chips({ items }: { items: string[] }) {
  return <>{items.map((i) => <span key={i} className={local.chip}>{i}</span>)}</>
}

function LessonCard({ m, canEdit, canManage, campaigns, onDone }: {
  m: Memory; canEdit: boolean; canManage: boolean; campaigns: Record<string, string>; onDone: () => void
}) {
  const { t, i18n } = useTranslation()
  const [correcting, setCorrecting] = useState(false)
  const [text, setText] = useState(m.lesson)
  const [scope, setScope] = useState<'brand' | 'context'>(m.scope)
  const [note, setNote] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' }) : '—')
  const overdue = m.status === 'active' && new Date(m.review_at).getTime() < Date.now()
  const canTouch = canEdit && (m.scope === 'context' || canManage)
  const c = m.conditions ?? {}
  const d = m.directives ?? {}

  async function rpc(name: string, args: Record<string, unknown>, ok: string) {
    setBusy(true)
    const { error } = await supabase.rpc(name, args)
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t(ok))
    setCorrecting(false)
    setConfirmDelete(false)
    onDone()
  }

  return (
    <li className={local.card} data-testid={`lesson-${m.id}`}>
      <div className={local.cardHead}>
        <span className={local.type}>{t(`mem.type.${m.type}`)}</span>
        <span className={`${local.scope} ${m.scope === 'brand' ? local.scopeBrand : ''}`}>{t(`mem.scope.${m.scope}`)}</span>
        {m.status !== 'active' && <span className={local.status}>{t(`mem.status.${m.status}`)}</span>}
        {overdue && <span className={local.overdue}>{t('mem.reviewOverdue')}</span>}
      </div>
      <p className={local.lesson}>{m.lesson}</p>
      {m.policy_conflict && <p className={local.conflict} role="note">{t('mem.conflict', { why: m.policy_conflict })}</p>}

      {(c.domains?.length || c.channels?.length || c.age_brackets?.length || c.languages?.length || c.income_tiers?.length) ? (
        <p className={local.meta}>
          {t('mem.appliesTo')}{' '}
          <Chips items={[...(c.domains ?? []).map((x) => t(`mem.domain.${x}`, x.replace(/_/g, ' '))), ...(c.channels ?? []), ...(c.age_brackets ?? []).map((a) => t('mem.age', { a })),
            ...(c.languages ?? []), ...(c.income_tiers ?? []).map((x) => t('mem.income', { x }))]} />
        </p>
      ) : m.scope === 'context' ? <p className={local.meta}>{t('mem.appliesWhenRelevant')}</p> : <p className={local.meta}>{t('mem.appliesEverywhere')}</p>}
      {(d.avoid_terms?.length || d.prefer_terms?.length || d.avoid_tones?.length || d.avoid_styles?.length) ? (
        <p className={local.meta}>
          {d.avoid_terms?.length ? <>{t('mem.avoid')} <Chips items={d.avoid_terms} /> </> : null}
          {d.prefer_terms?.length ? <>{t('mem.prefer')} <Chips items={d.prefer_terms} /> </> : null}
          {d.avoid_tones?.length ? <>{t('mem.avoidTone')} <Chips items={d.avoid_tones.map((x) => t(`mem.tone.${x}`, x))} /> </> : null}
          {d.avoid_styles?.length ? <>{t('mem.avoidStyle')} <Chips items={d.avoid_styles} /></> : null}
        </p>
      ) : null}

      <details className={local.provenance}>
        <summary>{t('mem.provenance', { count: m.evidence.length })}</summary>
        <ul>
          {m.evidence.map((e, i) => (
            <li key={i}>
              <strong>{t(`mem.evidence.${e.kind}`, e.kind)}</strong>
              {e.excerpt && <> · “{e.excerpt}”</>}
              {e.before && e.after && <span className={local.diff}>{t('mem.beforeAfter', { before: e.before, after: e.after })}</span>}
              {e.campaign_id && (
                <Link className={local.fromCampaign} to={`/campaigns/${e.campaign_id}`}>
                  {t('mem.fromCampaign', { name: campaigns[e.campaign_id] ? short(campaigns[e.campaign_id]) : t('mem.pastCampaign') })}
                </Link>
              )}
            </li>
          ))}
        </ul>
        <p className={local.meta}>
          {t(m.author_kind === 'system' ? 'mem.bySystem' : 'mem.byPerson')} · {t('mem.added', { when: day(m.created_at) })} ·{' '}
          {t('mem.reviewBy', { when: day(m.review_at) })}{m.expires_at ? ` · ${t('mem.expires', { when: day(m.expires_at) })}` : ''} ·{' '}
          {t('mem.confidence', { pct: pct(m.confidence) })} · {t('mem.used', { count: m.use_count })}
        </p>
      </details>

      {canTouch && m.status === 'proposed' && (
        <div className={local.actions}>
          <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy}
            onClick={() => rpc('review_brand_lesson', { p_memory: m.id, p_accept: true, p_note: null }, 'mem.confirmedToast')}>{t('mem.confirm')}</button>
          <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy}
            onClick={() => rpc('review_brand_lesson', { p_memory: m.id, p_accept: false, p_note: null }, 'mem.rejectedToast')}>{t('mem.reject')}</button>
        </div>
      )}
      {canTouch && m.status === 'active' && !correcting && (
        <div className={local.actions}>
          {overdue && <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy}
            onClick={() => rpc('review_brand_lesson', { p_memory: m.id, p_accept: true, p_note: null }, 'mem.confirmedToast')}>{t('mem.stillTrue')}</button>}
          <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => setCorrecting(true)}>{t('mem.correct')}</button>
          <button type="button" className={`${styles.btn} ${styles.ghost}`} disabled={busy}
            onClick={() => rpc('expire_brand_lesson', { p_memory: m.id }, 'mem.expiredToast')}>{t('mem.expire')}</button>
          <button type="button" className={`${styles.btn} ${confirmDelete ? styles.dangerSolid : styles.danger}`} disabled={busy}
            onClick={() => (confirmDelete ? rpc('delete_brand_lesson', { p_memory: m.id }, 'mem.deletedToast') : setConfirmDelete(true))}>
            {confirmDelete ? t('mem.deleteConfirm') : t('mem.delete')}
          </button>
        </div>
      )}
      {correcting && (
        <div className={local.correct}>
          <label className={styles.field}><span>{t('mem.lesson')}</span>
            <textarea className={styles.textarea} rows={2} value={text} onChange={(e) => setText(e.target.value)} /></label>
          <div className={local.row}>
            <label className={styles.field}><span>{t('mem.scopeLabel')}</span>
              <Select aria-label={t('mem.scopeLabel')} value={scope} onChange={setScope}
                options={[{ value: 'context', label: t('mem.scope.context') }, { value: 'brand', label: t('mem.scope.brand'), disabled: !canManage }]} /></label>
            <label className={styles.field}><span>{t('mem.whatWasWrong')}</span>
              <input className={styles.input} value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('mem.whatWasWrongPlaceholder')} /></label>
          </div>
          <div className={local.actions}>
            <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy || text.trim().length < 10 || note.trim().length < 10}
              onClick={() => rpc('correct_brand_lesson', { p_memory: m.id, p_lesson: text.trim(), p_scope: scope, p_conditions: null, p_directives: null, p_note: note.trim() }, 'mem.correctedToast')}>
              {t('mem.saveCorrection')}
            </button>
            <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => setCorrecting(false)}>{t('mem.cancel')}</button>
          </div>
        </div>
      )}
    </li>
  )
}

function AddLesson({ orgId, canManage, onDone }: { orgId: string; canManage: boolean; onDone: () => void }) {
  const { t } = useTranslation()
  const [type, setType] = useState<MemoryType>('BRAND_PREFERENCE')
  const [lesson, setLesson] = useState('')
  const [scope, setScope] = useState<'brand' | 'context'>('context')
  const [domains, setDomains] = useState<string[]>([])
  const [channels, setChannels] = useState<string[]>([])
  const [ages, setAges] = useState<string[]>([])
  const [avoid, setAvoid] = useState('')
  const [prefer, setPrefer] = useState('')
  const [tones, setTones] = useState<string[]>([])
  const [why, setWhy] = useState('')
  const [expires, setExpires] = useState('')
  const [busy, setBusy] = useState(false)
  const toggle = (arr: string[], set: (v: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])

  async function save() {
    setBusy(true)
    const conditions: Record<string, string[]> = {}
    if (scope === 'context') {
      if (domains.length) conditions.domains = domains
      if (channels.length) conditions.channels = channels
      if (ages.length) conditions.age_brackets = ages
    }
    const directives: Record<string, string[]> = {}
    if (list(avoid).length) directives.avoid_terms = list(avoid)
    if (list(prefer).length) directives.prefer_terms = list(prefer)
    if (tones.length) directives.avoid_tones = tones
    const { error } = await supabase.rpc('add_brand_lesson', {
      p_org: orgId, p_type: type, p_lesson: lesson.trim(), p_scope: scope, p_conditions: conditions, p_directives: directives,
      p_evidence_note: why.trim() || null, p_campaign: null, p_expires_at: expires ? new Date(expires).toISOString() : null,
    })
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('mem.addedToast'))
    setLesson(''); setDomains([]); setChannels([]); setAges([]); setAvoid(''); setPrefer(''); setTones([]); setWhy(''); setExpires('')
    onDone()
  }

  return (
    <section className={`${styles.panel} ${local.add}`} data-testid="add-lesson">
      <div className={styles.panelHead}><div><h2>{t('mem.addTitle')}</h2><p className={styles.panelSub}>{t('mem.addSub')}</p></div></div>
      <div className={local.row}>
        <label className={styles.field}><span>{t('mem.typeLabel')}</span>
          <Select aria-label={t('mem.typeLabel')} value={type} onChange={setType} options={TYPES.map((v) => ({ value: v, label: t(`mem.type.${v}`) }))} /></label>
        <label className={styles.field}><span>{t('mem.scopeLabel')}</span>
          <Select aria-label={t('mem.scopeLabel')} value={scope} onChange={setScope}
            options={[{ value: 'context', label: t('mem.scope.context') }, { value: 'brand', label: t('mem.scope.brand'), disabled: !canManage }]} /></label>
      </div>
      <label className={styles.field}><span>{t('mem.lesson')}</span>
        <textarea className={styles.textarea} rows={2} value={lesson} onChange={(e) => setLesson(e.target.value)} placeholder={t('mem.lessonPlaceholder')} /></label>
      {scope === 'context' && (
        <>
          <fieldset className={local.checks}><legend>{t('mem.domainsLabel')}</legend>
            {DOMAINS.map((v) => <label key={v}><input type="checkbox" checked={domains.includes(v)} onChange={() => toggle(domains, setDomains, v)} /> {t(`mem.domain.${v}`)}</label>)}
          </fieldset>
          <fieldset className={local.checks}><legend>{t('mem.channelsLabel')}</legend>
            {CHANNELS.map((c) => <label key={c}><input type="checkbox" checked={channels.includes(c)} onChange={() => toggle(channels, setChannels, c)} /> {c}</label>)}
          </fieldset>
          <fieldset className={local.checks}><legend>{t('mem.agesLabel')}</legend>
            {AGES.map((a) => <label key={a}><input type="checkbox" checked={ages.includes(a)} onChange={() => toggle(ages, setAges, a)} /> {a}</label>)}
          </fieldset>
        </>
      )}
      <div className={local.row}>
        <label className={styles.field}><span>{t('mem.avoidLabel')}</span>
          <input className={styles.input} value={avoid} onChange={(e) => setAvoid(e.target.value)} placeholder={t('mem.avoidPlaceholder')} /></label>
        <label className={styles.field}><span>{t('mem.preferLabel')}</span>
          <input className={styles.input} value={prefer} onChange={(e) => setPrefer(e.target.value)} placeholder={t('mem.preferPlaceholder')} /></label>
      </div>
      <fieldset className={local.checks}><legend>{t('mem.tonesLabel')}</legend>
        {TONES.map((v) => <label key={v}><input type="checkbox" checked={tones.includes(v)} onChange={() => toggle(tones, setTones, v)} /> {t(`mem.tone.${v}`)}</label>)}
      </fieldset>
      <div className={local.row}>
        <label className={styles.field}><span>{t('mem.whyLabel')}</span>
          <input className={styles.input} value={why} onChange={(e) => setWhy(e.target.value)} placeholder={t('mem.whyPlaceholder')} /></label>
        <label className={styles.field}><span>{t('mem.expiresLabel')}</span>
          <input type="date" className={styles.input} value={expires} onChange={(e) => setExpires(e.target.value)} /></label>
      </div>
      <p className={local.meta}>{t('mem.addNote')}</p>
      <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy || lesson.trim().length < 10} onClick={save}>{t('mem.add')}</button>
    </section>
  )
}

/** Brand memory: the organisation's lessons, why they exist, and the controls to review, correct, expire or delete them. */
export default function BrandMemory() {
  const { t } = useTranslation()
  const { active, can } = useOrg()
  const [rows, setRows] = useState<Memory[]>([])
  const [campaigns, setCampaigns] = useState<Record<string, string>>({})
  const [loaded, setLoaded] = useState(false)
  const [filter, setFilter] = useState<MemoryType | 'all'>('all')
  usePageLoading(!loaded)
  const canEdit = !!active && (can('create', active.id) || can('manage', active.id))
  const canManage = !!active && can('manage', active.id)

  const load = useCallback(async () => {
    if (!active) return
    const { data, error } = await supabase.from('brand_memories').select('*').eq('org_id', active.id).order('created_at', { ascending: false })
    setLoaded(true)
    if (toastLoadError(t, error, () => load())) return
    const memories = (data as Memory[]) ?? []
    setRows(memories)
    // Name the campaigns lessons came from; a missing name falls back to "a past campaign".
    const ids = [...new Set(memories.flatMap((m) => m.evidence.map((e) => e.campaign_id).filter((x): x is string => !!x)))]
    if (!ids.length) return
    const { data: named } = await supabase.from('campaigns').select('id, idea').in('id', ids)
    setCampaigns(Object.fromEntries(((named as { id: string; idea: string }[]) ?? []).map((c) => [c.id, c.idea])))
  }, [active, t])
  useEffect(() => { load() }, [load])

  const proposed = rows.filter((m) => m.status === 'proposed')
  const current = useMemo(() => rows.filter((m) => m.status === 'active' && (filter === 'all' || m.type === filter)), [rows, filter])
  const history = rows.filter((m) => ['superseded', 'expired', 'rejected'].includes(m.status))

  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('mem.eyebrow')}</span>
          <h1 className={styles.title}>{t('mem.title')}</h1>
          <p className={styles.subtitle}>{t('mem.subtitle')}</p>
        </div>
      </header>

      <p className={local.evalLine} data-testid="memory-eval">
        {t('mem.evalLine', { n: MEMORY_EVAL.tasks, before: pct(MEMORY_EVAL.followedWithout), after: pct(MEMORY_EVAL.followedWith) })}
      </p>

      {proposed.length > 0 && (
        <section className={`${styles.panel} ${local.review}`} data-testid="review-queue">
          <div className={styles.panelHead}><div><h2>{t('mem.reviewTitle', { count: proposed.length })}</h2><p className={styles.panelSub}>{t('mem.reviewSub')}</p></div></div>
          <ul className={local.cards}>{proposed.map((m) => <LessonCard key={m.id} m={m} canEdit={canEdit} canManage={canManage} campaigns={campaigns} onDone={load} />)}</ul>
        </section>
      )}

      <section className={styles.panel} data-testid="active-lessons">
        <div className={styles.panelHead}>
          <div><h2>{t('mem.activeTitle')}</h2><p className={styles.panelSub}>{t('mem.activeSub')}</p></div>
        </div>
        <nav className={local.filters} aria-label={t('mem.typeLabel')}>
          {(['all', ...TYPES] as const).map((v) => (
            <button key={v} type="button" className={`${local.filter} ${filter === v ? local.filterOn : ''}`} aria-pressed={filter === v} onClick={() => setFilter(v)}>
              {v === 'all' ? t('mem.all') : t(`mem.type.${v}`)}
            </button>
          ))}
        </nav>
        {current.length ? (
          <ul className={local.cards}>{current.map((m) => <LessonCard key={m.id} m={m} canEdit={canEdit} canManage={canManage} campaigns={campaigns} onDone={load} />)}</ul>
        ) : <p className={local.meta}>{loaded ? t('mem.empty') : ''}</p>}
        {history.length > 0 && (
          <details className={local.history}>
            <summary>{t('mem.history', { count: history.length })}</summary>
            <ul className={local.cards}>{history.map((m) => <LessonCard key={m.id} m={m} canEdit={false} canManage={false} campaigns={campaigns} onDone={load} />)}</ul>
          </details>
        )}
      </section>

      {canEdit && active && <AddLesson orgId={active.id} canManage={canManage} onDone={load} />}
    </div>
  )
}
