import { useTranslation } from 'react-i18next'

import { AD_TEMPLATES } from '../lib/adTemplates'
import Select from './Select'
import css from './TemplatePicker.module.css'

const humanize = (s: string) => s.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())

/**
 * An ad template by name, or "best fit" (empty), with a link to the gallery
 * that shows every template (components/TemplateGallery). `note` says what
 * picking one means where it's used.
 */
export default function TemplatePicker({
  value,
  onChange,
  onBrowse,
  note,
  wide = false,
}: {
  value: string
  onChange: (template: string) => void
  onBrowse: () => void
  note?: string
  wide?: boolean
}) {
  const { t } = useTranslation()
  return (
    <div className={`${css.pick} ${wide ? css.wide : ''}`}>
      <label className={css.field}>
        <span>
          {t('product.template')} <em>{t('product.optional')}</em>
        </span>
        <Select
          aria-label={t('product.template')}
          value={value}
          onChange={onChange}
          options={[{ value: '', label: t('tl.templateAuto') }, ...AD_TEMPLATES.map((id) => ({ value: id, label: humanize(id) }))]}
        />
      </label>
      <div className={css.foot}>
        <button type="button" className={`${css.help} link-wipe`} onClick={onBrowse}>
          {t('tg.link')}
        </button>
        {value && note && <small className={css.note}>{note}</small>}
      </div>
    </div>
  )
}
