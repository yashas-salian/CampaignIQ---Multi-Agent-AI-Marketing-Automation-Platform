import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { toastFailure, toastLoadError } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { useDescribe } from '../lib/segments'
import type { Segment, SegmentFilter } from '../lib/types'
import styles from '../styles/app.module.css'
import local from './Segments.module.css'

const list = (s: string) => s.split(',').map((x) => x.trim().toLowerCase()).filter(Boolean)

function Editor({ orgId, tags, initial, onDone, onCancel }: {
  orgId: string; tags: { tag: string; people: number }[]; initial: Segment | null; onDone: () => void; onCancel: () => void
}) {
  const { t, i18n } = useTranslation()
  const f = initial?.filter ?? {}
  const [name, setName] = useState(initial?.name ?? '')
  const [any, setAny] = useState<string[]>(f.tags_any ?? [])
  const [none, setNone] = useState<string[]>(f.tags_none ?? [])
  const [bought, setBought] = useState(f.purchased_within_days ? String(f.purchased_within_days) : '')
  const [notBought, setNotBought] = useState(f.not_purchased_within_days ? String(f.not_purchased_within_days) : '')
  const [products, setProducts] = useState((f.product_any ?? []).join(', '))
  const [countries, setCountries] = useState((f.country_any ?? []).join(', '))
  const [sameLanguage, setSameLanguage] = useState(f.match_campaign_language !== false)
  const [count, setCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)

  const filter: SegmentFilter = {}
  if (any.length) filter.tags_any = any
  if (none.length) filter.tags_none = none
  if (Number(bought) > 0) filter.purchased_within_days = Number(bought)
  if (Number(notBought) > 0) filter.not_purchased_within_days = Number(notBought)
  if (list(products).length) filter.product_any = list(products)
  if (list(countries).length) filter.country_any = list(countries)
  if (!sameLanguage) filter.match_campaign_language = false
  const key = JSON.stringify(filter)

  useEffect(() => {
    const id = window.setTimeout(async () => {
      const { data } = await supabase.rpc('segment_count', { p_org: orgId, p_filter: JSON.parse(key), p_language: i18n.language.slice(0, 2) })
      setCount(typeof data === 'number' ? data : null)
    }, 300)
    return () => window.clearTimeout(id)
  }, [orgId, key, i18n.language])

  const toggle = (arr: string[], set: (v: string[]) => void, v: string) => set(arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])

  async function save() {
    setBusy(true)
    const row = { org_id: orgId, name: name.trim(), filter, updated_at: new Date().toISOString() }
    const { error } = initial
      ? await supabase.from('segments').update(row).eq('id', initial.id)
      : await supabase.from('segments').insert(row)
    setBusy(false)
    if (toastFailure(t, error)) return
    toast.success(t('seg.saved'))
    onDone()
  }

  return (
    <div className={local.editor} data-testid="segment-editor">
      <label className={styles.field}><span>{t('seg.name')}</span>
        <input className={styles.input} maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder={t('seg.namePlaceholder')} /></label>
      {tags.length > 0 && (
        <>
          <fieldset className={local.chips}><legend>{t('seg.tagsAny')}</legend>
            {tags.map(({ tag }) => (
              <button key={tag} type="button" aria-pressed={any.includes(tag)} className={`${local.chip} ${any.includes(tag) ? local.on : ''}`}
                onClick={() => toggle(any, setAny, tag)}>{tag}</button>
            ))}
          </fieldset>
          <fieldset className={local.chips}><legend>{t('seg.tagsNone')}</legend>
            {tags.map(({ tag }) => (
              <button key={tag} type="button" aria-pressed={none.includes(tag)} className={`${local.chip} ${none.includes(tag) ? local.on : ''}`}
                onClick={() => toggle(none, setNone, tag)}>{tag}</button>
            ))}
          </fieldset>
        </>
      )}
      <div className={local.grid}>
        <label className={styles.field}><span>{t('seg.bought')}</span>
          <input className={styles.input} type="number" min={1} value={bought} onChange={(e) => setBought(e.target.value)} placeholder="90" /></label>
        <label className={styles.field}><span>{t('seg.notBought')}</span>
          <input className={styles.input} type="number" min={1} value={notBought} onChange={(e) => setNotBought(e.target.value)} placeholder="180" /></label>
        <label className={styles.field}><span>{t('seg.products')}</span>
          <input className={styles.input} value={products} onChange={(e) => setProducts(e.target.value)} placeholder={t('seg.productsPlaceholder')} /></label>
        <label className={styles.field}><span>{t('seg.countries')}</span>
          <input className={styles.input} value={countries} onChange={(e) => setCountries(e.target.value)} placeholder="India, Portugal" /></label>
      </div>
      <label className={local.check}>
        <input type="checkbox" checked={sameLanguage} onChange={(e) => setSameLanguage(e.target.checked)} />
        <span>{t('seg.sameLanguage')}</span>
      </label>
      <p className={local.count} data-testid="segment-count" aria-live="polite">{count === null ? '…' : t('seg.count', { count })}</p>
      <div className={local.actions}>
        <button type="button" className={`${styles.btn} ${styles.primary}`} disabled={busy || !name.trim()} onClick={save}>{t('seg.save')}</button>
        <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={onCancel}>{t('ct.close')}</button>
      </div>
    </div>
  )
}

/** Contacts → Segments: saved filters a campaign can email, with how many people each reaches now. */
export default function Segments({ orgId, canEdit, tags }: { orgId: string; canEdit: boolean; tags: { tag: string; people: number }[] }) {
  const { t, i18n } = useTranslation()
  const describe = useDescribe()
  const [rows, setRows] = useState<Segment[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [editing, setEditing] = useState<Segment | 'new' | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const load = useCallback(async () => {
    const { data, error } = await supabase.from('segments').select('id,org_id,name,filter,created_at').eq('org_id', orgId).order('created_at')
    if (toastLoadError(t, error, () => load())) return
    const segs = (data as Segment[]) ?? []
    setRows(segs)
    const lang = i18n.language.slice(0, 2)
    const found = await Promise.all(segs.map((s) => supabase.rpc('segment_count', { p_org: orgId, p_filter: s.filter, p_language: lang })))
    setCounts(Object.fromEntries(segs.map((s, i) => [s.id, (found[i].data as number) ?? 0])))
  }, [orgId, t, i18n.language])
  useEffect(() => { load() }, [load])

  async function remove(id: string) {
    const { error } = await supabase.from('segments').delete().eq('id', id)
    if (toastFailure(t, error)) return
    setConfirmDelete(null)
    load()
  }

  return (
    <section id="segments" className={styles.panel} data-testid="segments">
      <div className={styles.panelHead}>
        <div><h2>{t('seg.title')}</h2><p className={styles.panelSub}>{t('seg.sub')}</p></div>
        {canEdit && editing === null && (
          <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => setEditing('new')}>{t('seg.new')}</button>
        )}
      </div>
      {editing !== null && (
        <Editor orgId={orgId} tags={tags} initial={editing === 'new' ? null : editing} onCancel={() => setEditing(null)}
          onDone={() => { setEditing(null); load() }} />
      )}
      {rows.length ? (
        <ul className={local.list}>
          {rows.map((s) => (
            <li key={s.id} className={local.row} data-testid={`segment-${s.id}`}>
              <div className={local.what}>
                <strong>{s.name}</strong>
                <span className={local.meta}>{describe(s.filter)}</span>
              </div>
              <span className={local.people}>{t('seg.count', { count: counts[s.id] ?? 0 })}</span>
              {canEdit && (
                <div className={local.actions}>
                  <button type="button" className={`${styles.btn} ${styles.ghost} ${local.small}`} onClick={() => setEditing(s)}>{t('seg.edit')}</button>
                  <button type="button" className={`${styles.btn} ${confirmDelete === s.id ? styles.dangerSolid : styles.danger} ${local.small}`}
                    onClick={() => (confirmDelete === s.id ? remove(s.id) : setConfirmDelete(s.id))}>
                    {confirmDelete === s.id ? t('seg.deleteConfirm') : t('seg.delete')}
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        editing === null && <p className={local.meta}>{t('seg.empty')}</p>
      )}
    </section>
  )
}
