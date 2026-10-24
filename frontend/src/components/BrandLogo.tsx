import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { toast } from '../lib/toast'
import { toastFailure } from '../lib/notify'
import styles from '../styles/app.module.css'
import css from './BrandLogo.module.css'

const BUCKET = 'brand-logos'
const TYPES: Record<string, string> = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' }
const MAX_BYTES = 1024 * 1024 // the bucket's limit (migration 20261024000200)

/**
 * The organisation's logo, placed on every finished ad (src/tools/ad_composer.py).
 * Saved on pick: uploaded to the private brand-logos bucket under the org's
 * folder, then brand_kits.logo_path points at it. Owners/admins edit.
 */
export default function BrandLogo({ orgId, path, editable, onChange }: {
  orgId: string
  path: string | null
  editable: boolean
  onChange: (path: string | null) => void
}) {
  const { t } = useTranslation()
  const input = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!path) {
      setPreview(null)
      return
    }
    let live = true
    supabase.storage
      .from(BUCKET)
      .createSignedUrl(path, 3600)
      .then(({ data }) => live && setPreview(data?.signedUrl ?? null))
    return () => {
      live = false
    }
  }, [path])

  async function save(next: string | null) {
    const { error } = await supabase
      .from('brand_kits')
      .upsert({ org_id: orgId, logo_path: next, updated_at: new Date().toISOString() })
    if (toastFailure(t, error)) return false
    onChange(next)
    return true
  }

  async function pick(file: File | undefined) {
    if (!file) return
    const ext = TYPES[file.type]
    if (!ext) return toast.error(t('brand.logoType'))
    if (file.size > MAX_BYTES) return toast.error(t('brand.logoSize'))
    setBusy(true)
    // A new name per upload, so ads and previews never show a cached old logo.
    const next = `${orgId}/logo-${Date.now()}.${ext}`
    const { error } = await supabase.storage.from(BUCKET).upload(next, file, { contentType: file.type })
    if (!toastFailure(t, error) && (await save(next))) {
      if (path) await supabase.storage.from(BUCKET).remove([path])
      toast.success(t('brand.logoSaved'))
    }
    setBusy(false)
    if (input.current) input.current.value = ''
  }

  async function remove() {
    if (!path) return
    setBusy(true)
    if (await save(null)) {
      await supabase.storage.from(BUCKET).remove([path])
      toast.success(t('brand.logoRemoved'))
    }
    setBusy(false)
  }

  return (
    <div className={styles.field}>
      <span>{t('brand.logo')}</span>
      <div className={css.row}>
        <div className={css.chip} aria-hidden={!preview}>
          {preview ? <img src={preview} alt={t('brand.logoAlt')} /> : <span className={styles.muted}>{t('brand.noLogo')}</span>}
        </div>
        {editable && (
          <div className={css.actions}>
            <input
              ref={input}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className={css.file}
              aria-label={t('brand.uploadLogo')}
              disabled={busy}
              onChange={(e) => pick(e.target.files?.[0])}
            />
            <button type="button" className={`${styles.btn} ${css.small}`} disabled={busy} onClick={() => input.current?.click()}>
              {path ? t('brand.replaceLogo') : t('brand.uploadLogo')}
            </button>
            {path && (
              <button type="button" className={`${styles.btn} ${css.small}`} disabled={busy} onClick={remove}>
                {t('brand.removeLogo')}
              </button>
            )}
          </div>
        )}
      </div>
      <p className={styles.muted}>{t('brand.logoHint')}</p>
    </div>
  )
}
