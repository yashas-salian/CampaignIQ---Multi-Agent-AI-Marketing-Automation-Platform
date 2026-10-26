import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import BrandLogo from './BrandLogo'
import { supabase } from '../lib/supabaseClient'
import { useOrg } from '../lib/useOrg'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'

interface Kit {
  voice: string
  preferred_words: string[]
  forbidden_words: string[]
  required_phrase: string | null
  brand_color: string | null
  logo_path: string | null
  postal_address: string | null
  privacy_url: string | null
}

const EMPTY: Kit = { voice: '', preferred_words: [], forbidden_words: [], required_phrase: null, brand_color: null, logo_path: null, postal_address: null, privacy_url: null }
const toList = (s: string) => s.split(',').map((w) => w.trim()).filter(Boolean)

/** How campaigns in this organisation should sound. Owners/admins edit; everyone else reads. */
export default function BrandKitSettings() {
  const { t } = useTranslation()
  const { active, can } = useOrg()
  const [kit, setKit] = useState<Kit>(EMPTY)
  const [preferred, setPreferred] = useState('')
  const [forbidden, setForbidden] = useState('')
  const editable = can('manage')

  useEffect(() => {
    if (!active) return
    supabase
      .from('brand_kits')
      .select('voice,preferred_words,forbidden_words,required_phrase,brand_color,logo_path,postal_address,privacy_url')
      .eq('org_id', active.id)
      .maybeSingle()
      .then(({ data, error }) => {
        if (toastFailure(t, error)) return
        const k = (data as Kit | null) ?? EMPTY
        setKit(k)
        setPreferred(k.preferred_words.join(', '))
        setForbidden(k.forbidden_words.join(', '))
      })
  }, [active, t])

  async function save(e: FormEvent) {
    e.preventDefault()
    if (!active) return
    const { error } = await supabase.from('brand_kits').upsert({
      org_id: active.id,
      voice: kit.voice,
      preferred_words: toList(preferred),
      forbidden_words: toList(forbidden),
      required_phrase: kit.required_phrase?.trim() || null,
      brand_color: kit.brand_color || null,
      postal_address: kit.postal_address?.trim() || null,
      privacy_url: kit.privacy_url?.trim() || null,
      updated_at: new Date().toISOString(),
    })
    if (!toastFailure(t, error)) toast.success(t('brand.savedToast'))
  }

  return (
    <form className={local.team} onSubmit={save}>
      <label className={styles.field}>
        <span>{t('brand.voice')}</span>
        <textarea
          className={styles.textarea}
          rows={3}
          maxLength={1000}
          disabled={!editable}
          placeholder={t('brand.voicePlaceholder')}
          value={kit.voice}
          onChange={(e) => setKit({ ...kit, voice: e.target.value })}
        />
      </label>
      <div className={local.policyGrid}>
        <label className={styles.field}>
          <span>{t('brand.preferred')}</span>
          <input className={styles.input} disabled={!editable} value={preferred} onChange={(e) => setPreferred(e.target.value)} placeholder="home-cooked, fresh" />
        </label>
        <label className={styles.field}>
          <span>{t('brand.forbidden')}</span>
          <input className={styles.input} disabled={!editable} value={forbidden} onChange={(e) => setForbidden(e.target.value)} placeholder="cheap, guaranteed" />
        </label>
        <label className={styles.field}>
          <span>{t('brand.required')}</span>
          <input
            className={styles.input}
            maxLength={80}
            disabled={!editable}
            value={kit.required_phrase ?? ''}
            onChange={(e) => setKit({ ...kit, required_phrase: e.target.value })}
            placeholder="#MadeWithAcme"
          />
        </label>
        <label className={styles.field}>
          <span>{t('brand.color')}</span>
          <input
            className={styles.input}
            type="color"
            disabled={!editable}
            value={kit.brand_color ?? '#ff6b3d'}
            onChange={(e) => setKit({ ...kit, brand_color: e.target.value })}
            style={{ padding: 4, height: 44 }}
          />
        </label>
      </div>
      <div className={local.policyGrid}>
        <label className={styles.field}>
          <span>{t('brand.postal')}</span>
          <textarea
            className={styles.textarea}
            rows={2}
            maxLength={300}
            disabled={!editable}
            value={kit.postal_address ?? ''}
            onChange={(e) => setKit({ ...kit, postal_address: e.target.value })}
            placeholder={t('brand.postalPlaceholder')}
          />
        </label>
        <label className={styles.field}>
          <span>{t('brand.privacy')}</span>
          <input
            className={styles.input}
            type="url"
            maxLength={500}
            disabled={!editable}
            value={kit.privacy_url ?? ''}
            onChange={(e) => setKit({ ...kit, privacy_url: e.target.value })}
            placeholder="https://yourbrand.com/privacy"
          />
        </label>
      </div>
      <p className={styles.muted}>{t('brand.postalWhy')}</p>
      {active && (
        <BrandLogo orgId={active.id} path={kit.logo_path} editable={editable} onChange={(logo_path) => setKit((k) => ({ ...k, logo_path }))} />
      )}
      <p className={styles.muted}>{t('brand.how')}</p>
      {editable && (
        <div className={local.inline}>
          <button className={`${styles.btn} ${styles.primary}`}>{t('brand.save')}</button>
        </div>
      )}
    </form>
  )
}
