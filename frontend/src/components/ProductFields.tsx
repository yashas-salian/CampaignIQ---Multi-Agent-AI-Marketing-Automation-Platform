import { useEffect, useId, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { PRODUCT_PHOTO_MAX_BYTES, PRODUCT_PHOTO_TYPES, TAGLINE_MAX, isWebLink } from '../lib/product'
import styles from './ProductFields.module.css'

type Props = {
  photo: File | null
  onPhoto: (file: File | null) => void
  tagline: string
  onTagline: (value: string) => void
  /** The call-to-action link; left out (Tools page) when not given. */
  link?: string
  onLink?: (value: string) => void
  /** Another field set beside the tagline (the Tools page's template picker). */
  extra?: ReactNode
}

export function ProductFields({ photo, onPhoto, tagline, onTagline, link, onLink, extra }: Props) {
  const { t } = useTranslation()
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [photoError, setPhotoError] = useState('')
  const [dragging, setDragging] = useState(false)
  const ids = { photo: useId(), tagline: useId(), link: useId(), linkError: useId() }
  const linkBad = !isWebLink(link ?? '')

  useEffect(() => {
    if (!photo) {
      setPreview(null)
      return
    }
    const url = URL.createObjectURL(photo)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [photo])

  function take(file: File | undefined) {
    if (!file) return
    if (!PRODUCT_PHOTO_TYPES.includes(file.type)) {
      setPhotoError(t('product.photoType'))
      return
    }
    if (file.size > PRODUCT_PHOTO_MAX_BYTES) {
      setPhotoError(t('product.photoSize'))
      return
    }
    setPhotoError('')
    onPhoto(file)
  }

  function onDrop(e: DragEvent<HTMLButtonElement>) {
    e.preventDefault()
    setDragging(false)
    take(e.dataTransfer.files?.[0])
  }

  return (
    <div className={styles.row}>
      <button
        type="button"
        id={ids.photo}
        className={`${styles.photo} ${dragging ? styles.dragging : ''} ${preview ? styles.filled : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-label={preview ? t('product.photoChange') : t('product.photoPick')}
        data-testid="product-photo"
      >
        {preview ? (
          <img src={preview} alt="" className={styles.thumb} />
        ) : (
          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={styles.icon}>
            <rect x="3" y="5" width="18" height="14" rx="3" stroke="currentColor" strokeWidth="1.7" />
            <circle cx="9" cy="10" r="1.8" stroke="currentColor" strokeWidth="1.6" />
            <path d="M4 17l5-4.5 3.5 3 3-2.5L20 17" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
        )}
        <span className={styles.photoLabel}>
          <strong>{preview ? t('product.photoChange') : t('product.photoPick')}</strong>
          <small>{photoError || (photo ? photo.name : t('product.photoHint'))}</small>
        </span>
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={PRODUCT_PHOTO_TYPES.join(',')}
        hidden
        onChange={(e) => {
          take(e.target.files?.[0])
          e.target.value = ''
        }}
        data-testid="product-photo-input"
      />
      <div className={styles.fields}>
        <label className={styles.field} htmlFor={ids.tagline}>
          <span>
            {t('product.tagline')} <em>{t('product.optional')}</em>
          </span>
          <input
            id={ids.tagline}
            value={tagline}
            maxLength={TAGLINE_MAX}
            onChange={(e) => onTagline(e.target.value)}
            placeholder={t('product.taglinePlaceholder')}
          />
          <small className={styles.count}>{tagline.length}/{TAGLINE_MAX}</small>
        </label>
        {onLink && (<label className={styles.field} htmlFor={ids.link}>
          <span>
            {t('product.link')} <em>{t('product.optional')}</em>
          </span>
          <input
            id={ids.link}
            type="url"
            inputMode="url"
            value={link}
            onChange={(e) => onLink(e.target.value)}
            placeholder="https://"
            aria-invalid={linkBad || undefined}
            aria-describedby={linkBad ? ids.linkError : undefined}
          />
          {linkBad && (
            <small id={ids.linkError} className={styles.error}>
              {t('product.linkInvalid')}
            </small>
          )}
        </label>)}
        {extra}
      </div>
    </div>
  )
}
