import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'

const CAPABILITIES = ['llm', 'image', 'judge'] as const

interface MaskedKey {
  capability: string
  masked_key: string
  updated_at: string
}

interface Template {
  template_type: 'image' | 'email'
  image_base64: string | null
  email_html: string | null
  updated_at: string
}

export default function Settings() {
  const { t } = useTranslation()
  const { session } = useSession()
  const [keys, setKeys] = useState<Record<string, MaskedKey>>({})
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const [templates, setTemplates] = useState<Record<string, Template>>({})
  const [emailHtml, setEmailHtml] = useState('')
  const [templateMessage, setTemplateMessage] = useState<string | null>(null)
  const [savingTemplate, setSavingTemplate] = useState<'image' | 'email' | null>(null)

  async function load() {
    const { data } = await supabase.from('provider_keys_masked').select('*')
    const byCapability: Record<string, MaskedKey> = {}
    for (const row of (data as MaskedKey[]) ?? []) {
      byCapability[row.capability] = row
    }
    setKeys(byCapability)
  }

  async function loadTemplates() {
    const { data } = await supabase.from('templates').select('*')
    const byType: Record<string, Template> = {}
    for (const row of (data as Template[]) ?? []) {
      byType[row.template_type] = row
    }
    setTemplates(byType)
    setEmailHtml(byType.email?.email_html ?? '')
  }

  useEffect(() => {
    load()
    loadTemplates()
  }, [])

  async function uploadImageTemplate(file: File) {
    const userId = session?.user.id
    if (!userId) return
    setSavingTemplate('image')
    setTemplateMessage(null)

    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve((reader.result as string).split(',')[1])
      reader.onerror = reject
      reader.readAsDataURL(file)
    })

    const { error } = await supabase
      .from('templates')
      .upsert({ user_id: userId, template_type: 'image', image_base64: base64 }, { onConflict: 'user_id,template_type' })

    setSavingTemplate(null)
    setTemplateMessage(error ? `Failed: ${error.message}` : 'Image template saved.')
    if (!error) await loadTemplates()
  }

  async function saveEmailTemplate() {
    const userId = session?.user.id
    if (!userId) return
    setSavingTemplate('email')
    setTemplateMessage(null)

    const { error } = await supabase
      .from('templates')
      .upsert({ user_id: userId, template_type: 'email', email_html: emailHtml }, { onConflict: 'user_id,template_type' })

    setSavingTemplate(null)
    setTemplateMessage(error ? `Failed: ${error.message}` : 'Email template saved.')
    if (!error) await loadTemplates()
  }

  async function submit(capability: string) {
    const apiKey = inputs[capability]
    if (!apiKey) return
    setSubmitting(capability)
    setMessage(null)

    const { data, error } = await supabase.functions.invoke('submit-provider-key', {
      body: { capability, api_key: apiKey },
    })

    setSubmitting(null)
    if (error) {
      setMessage(`Failed: ${error.message}`)
      return
    }
    setMessage(`Saved ${capability} key (${data.masked_key})`)
    setInputs((prev) => ({ ...prev, [capability]: '' }))
    await load()
  }

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <h1 className="text-2xl font-semibold">{t('settings.title')}</h1>
      <p className="text-sm text-gray-500">{t('settings.subtitle')}</p>

      {message && <p className="text-sm text-purple-600">{message}</p>}

      {CAPABILITIES.map((capability) => (
        <div key={capability} className="border rounded-lg p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="font-medium capitalize">{capability}</span>
            <span className="text-sm text-gray-500 font-mono">{keys[capability]?.masked_key ?? t('settings.notSet')}</span>
          </div>
          <div className="flex gap-2">
            <input
              type="password"
              placeholder={t('settings.keyPlaceholder')}
              value={inputs[capability] ?? ''}
              onChange={(e) => setInputs((prev) => ({ ...prev, [capability]: e.target.value }))}
              className="flex-1 border rounded-lg p-2 text-sm"
            />
            <button
              onClick={() => submit(capability)}
              disabled={submitting === capability}
              className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm disabled:opacity-50"
            >
              {submitting === capability ? t('settings.saving') : t('settings.save')}
            </button>
          </div>
        </div>
      ))}

      <div className="border-t pt-6 space-y-4">
        <h2 className="text-xl font-semibold">{t('settings.templatesTitle')}</h2>
        <p className="text-sm text-gray-500">{t('settings.templatesSubtitle')}</p>

        {templateMessage && <p className="text-sm text-purple-600">{templateMessage}</p>}

        <div className="border rounded-lg p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="font-medium">{t('settings.imageTemplateLabel')}</span>
            <span className="text-sm text-gray-500">{templates.image ? t('settings.set') : t('settings.notSet')}</span>
          </div>
          {templates.image?.image_base64 && (
            <img
              src={`data:image/png;base64,${templates.image.image_base64}`}
              alt="Current image template"
              className="max-h-32 rounded mb-2"
            />
          )}
          <input
            type="file"
            accept="image/*"
            onChange={(e) => e.target.files?.[0] && uploadImageTemplate(e.target.files[0])}
            disabled={savingTemplate === 'image'}
            className="text-sm"
          />
        </div>

        <div className="border rounded-lg p-4">
          <div className="flex justify-between items-center mb-2">
            <span className="font-medium">{t('settings.emailTemplateLabel')}</span>
            <span className="text-sm text-gray-500">{templates.email ? t('settings.set') : t('settings.notSet')}</span>
          </div>
          <textarea
            placeholder={t('settings.emailTemplatePlaceholder', { placeholder: '{{copy}}' })}
            value={emailHtml}
            onChange={(e) => setEmailHtml(e.target.value)}
            rows={6}
            className="w-full border rounded-lg p-2 text-sm font-mono mb-2"
          />
          <button
            onClick={saveEmailTemplate}
            disabled={savingTemplate === 'email'}
            className="px-4 py-2 rounded-lg bg-purple-600 text-white text-sm disabled:opacity-50"
          >
            {savingTemplate === 'email' ? t('settings.saving') : t('settings.save')}
          </button>
        </div>
      </div>
    </div>
  )
}
