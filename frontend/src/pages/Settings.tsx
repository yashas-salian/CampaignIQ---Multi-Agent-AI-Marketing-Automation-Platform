import type { CSSProperties, DragEvent, ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import ApiSettings from '../components/ApiSettings'
import AuditLog from '../components/AuditLog'
import BillingSettings from '../components/BillingSettings'
import BrandKitSettings from '../components/BrandKitSettings'
import EmailSendingSettings from '../components/EmailSendingSettings'
import UsageStats from '../components/UsageStats'
import PrivacySettings from '../components/PrivacySettings'
import TeamSettings from '../components/TeamSettings'
import { toast } from '../lib/toast'
import { signOutWithToast, toastFailure, toastLoadError } from '../lib/notify'
import { usePageLoading } from '../lib/loading'
import { useSectionSpy } from '../lib/sectionSpy'
import { useOrg } from '../lib/useOrg'
import { isValidUsername, normalizeUsername, saveUsername, usernameOf } from '../lib/profile'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import { setSettingsNav } from '../lib/shell'
import styles from '../styles/app.module.css'
import local from './Settings.module.css'

const CAPABILITIES = ['llm', 'image', 'judge'] as const
type KeyCapability = (typeof CAPABILITIES)[number]
const FREE_ROUNDS = 3
const PAID_ROUNDS = 10

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

type Notice = { kind: 'ok' | 'error'; text: string } | null

const KEY_ICONS: Record<KeyCapability, ReactNode> = {
  llm: <path d="M4 6h16M4 12h10M4 18h7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />,
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="2" />
      <path d="M3 15l5-5 4 4 3-3 6 6" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
    </>
  ),
  judge: <path d="M12 3l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 16.4 6.7 19.1l1-5.8L3.5 9.2l5.9-.9z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />,
}

// Inline only for field validation (an invalid username); results are toasts.
function NoticeLine({ notice, onClose }: { notice: Notice; onClose: () => void }) {
  const { t } = useTranslation()
  if (!notice) return null
  return (
    <p className={`${styles.toast} ${notice.kind === 'ok' ? styles.toastOk : styles.toastError}`} role={notice.kind === 'ok' ? 'status' : 'alert'}>
      {notice.text}
      <button type="button" onClick={onClose} aria-label={t('toast.dismiss')}>
        ×
      </button>
    </p>
  )
}

export default function Settings() {
  const { can: canInOrg } = useOrg()
  const { t, i18n } = useTranslation()
  const { session } = useSession()
  const [keys, setKeys] = useState<Record<string, MaskedKey>>({})
  const [inputs, setInputs] = useState<Record<string, string>>({})
  const [reveal, setReveal] = useState<Record<string, boolean>>({})
  const [submitting, setSubmitting] = useState<string | null>(null)
  const [tier, setTier] = useState<'free' | 'subscribed'>('free')

  const [templates, setTemplates] = useState<Record<string, Template>>({})
  const [emailHtml, setEmailHtml] = useState('')
  const [savingTemplate, setSavingTemplate] = useState<'image' | 'email' | null>(null)
  const [dragging, setDragging] = useState(false)
  const savedUsername = usernameOf(session?.user)
  const [usernameDraft, setUsernameDraft] = useState('')
  const [savingName, setSavingName] = useState(false)
  const [nameNotice, setNameNotice] = useState<Notice>(null)

  // Fill the field once the session (and so the saved username) has loaded.
  useEffect(() => {
    setUsernameDraft(savedUsername ?? '')
  }, [savedUsername])

  const load = useCallback(async () => {
    const [{ data, error }, { data: sub }] = await Promise.all([
      supabase.from('provider_keys_masked').select('*'),
      supabase.from('subscriptions').select('status').maybeSingle(),
    ])
    if (toastLoadError(t, error, () => load())) return
    const byCapability: Record<string, MaskedKey> = {}
    for (const row of (data as MaskedKey[]) ?? []) byCapability[row.capability] = row
    setKeys(byCapability)
    setTier(sub?.status === 'subscribed' ? 'subscribed' : 'free')
  }, [t])

  const loadTemplates = useCallback(async () => {
    const { data, error } = await supabase.from('templates').select('*')
    if (toastLoadError(t, error, () => loadTemplates())) return
    const byType: Record<string, Template> = {}
    for (const row of (data as Template[]) ?? []) byType[row.template_type] = row
    setTemplates(byType)
    setEmailHtml(byType.email?.email_html ?? '')
  }, [t])

  // Cover the page until keys and templates are in, so no field shows empty first.
  const [loaded, setLoaded] = useState(false)
  usePageLoading(!loaded)
  useEffect(() => {
    Promise.all([load(), loadTemplates()]).finally(() => setLoaded(true))
  }, [load, loadTemplates])

  // Deleting the row also deletes its Vault secret (database trigger); campaigns
  // then fall back to the plan's own providers.
  async function removeKey(capability: KeyCapability) {
    setSubmitting(capability)
    const { error } = await supabase.from('provider_keys').delete().eq('capability', capability)
    setSubmitting(null)
    if (!toastFailure(t, error)) toast.success(t('st.removed', { capability: t(`st.cap_${capability}`) }))
    await load()
  }

  async function submit(capability: KeyCapability) {
    const apiKey = inputs[capability]?.trim()
    if (!apiKey) return
    setSubmitting(capability)
    const { data, error } = await supabase.functions.invoke('submit-provider-key', {
      body: { capability, api_key: apiKey },
    })
    setSubmitting(null)
    if (toastFailure(t, error)) return
    toast.success(t('st.saved', { capability: t(`st.cap_${capability}`), masked: data.masked_key }))
    setInputs((prev) => ({ ...prev, [capability]: '' }))
    setReveal((prev) => ({ ...prev, [capability]: false }))
    await load()
  }

  async function uploadImageTemplate(file: File) {
    const userId = session?.user.id
    if (!userId) return
    if (!file.type.startsWith('image/')) {
      toast.error(t('st.notImage'))
      return
    }
    setSavingTemplate('image')
    let base64: string
    try {
      base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve((reader.result as string).split(',')[1])
        reader.onerror = () => reject(reader.error ?? new Error(t('st.fileUnreadable')))
        reader.readAsDataURL(file)
      })
    } catch (readError) {
      setSavingTemplate(null)
      toastFailure(t, readError)
      return
    }
    const { error } = await supabase
      .from('templates')
      .upsert({ user_id: userId, template_type: 'image', image_base64: base64 }, { onConflict: 'user_id,template_type' })
    setSavingTemplate(null)
    if (!toastFailure(t, error)) toast.success(t('st.imageSaved'))
    if (!error) await loadTemplates()
  }

  async function saveEmailTemplate() {
    const userId = session?.user.id
    if (!userId) return
    setSavingTemplate('email')
    const { error } = await supabase
      .from('templates')
      .upsert({ user_id: userId, template_type: 'email', email_html: emailHtml }, { onConflict: 'user_id,template_type' })
    setSavingTemplate(null)
    if (!toastFailure(t, error)) toast.success(t('st.emailSaved'))
    if (!error) await loadTemplates()
  }

  function onDrop(e: DragEvent<HTMLLabelElement>) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) uploadImageTemplate(file)
  }

  async function submitUsername() {
    if (!isValidUsername(usernameDraft)) {
      setNameNotice({ kind: 'error', text: t('st.usernameInvalid') })
      return
    }
    setSavingName(true)
    setNameNotice(null)
    const { error } = await saveUsername(usernameDraft)
    setSavingName(false)
    // On success Supabase emits USER_UPDATED, so every useSession() (greeting, etc.) picks up the new name.
    if (!toastFailure(t, error)) toast.success(t('st.usernameSaved'))
  }

  // The backend swaps "{{copy}}" for the ad copy (distribution_email.py); preview the same way.
  const previewDoc = useMemo(() => {
    const sample = `<p style="margin:0;padding:12px 14px;border:1px dashed #e4521f;border-radius:8px;font-family:sans-serif">${t('st.previewSample')}</p>`
    return emailHtml.trim() ? emailHtml.split('{{copy}}').join(sample) : ''
  }, [emailHtml, t])

  const fmt = (iso: string) => new Date(iso).toLocaleDateString(i18n.language, { day: 'numeric', month: 'short', year: 'numeric' })
  const canManage = canInOrg('manage')
  const sections = [
    { id: 'account', label: t('st.navAccount') },
    { id: 'team', label: t('org.team') },
    { id: 'brand', label: t('brand.title') },
    { id: 'email', label: t('em.title') },
    { id: 'billing', label: t('billing.title') },
    ...(canManage ? [{ id: 'usage', label: t('obs.title') }, { id: 'api', label: t('api.title') }, { id: 'audit', label: t('audit.title') }] : []),
    { id: 'keys', label: t('st.navKeys') },
    { id: 'templates', label: t('st.navTemplates') },
    { id: 'privacy', label: t('privacy.title') },
  ]

  // The sections are listed in the app sidebar under Settings, with the one in view marked.
  const [current, pick] = useSectionSpy(sections.map((s) => s.id))
  const sectionsKey = JSON.stringify(sections)
  useEffect(() => {
    setSettingsNav({ sections: JSON.parse(sectionsKey) as { id: string; label: string }[], current, pick })
  }, [sectionsKey, current, pick])
  useEffect(() => () => setSettingsNav(null), [])


  return (
    <div className={styles.page}>
      <header className={`${styles.header} ${styles.enter}`}>
        <div>
          <span className={styles.eyebrow}>{t('common.settings')}</span>
          <h1 className={styles.title}>{t('st.title')}</h1>
          <p className={styles.subtitle}>{t('st.subtitle')}</p>
        </div>
      </header>


      <div className={local.layout}>

        <div className={styles.stack}>
          {/* Account */}
          <section id="account" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 1 } as CSSProperties}>
            <div className={styles.panelHead}>
              <h2>{t('st.navAccount')}</h2>
              <span className={`${local.tier} ${tier === 'subscribed' ? local.tierPaid : ''}`}>
                {tier === 'subscribed' ? t('dash.planSubscribed') : t('dash.planFree')}
              </span>
            </div>
            <dl className={local.account}>
              <div>
                <dt>{t('st.email')}</dt>
                <dd>{session?.user.email ?? '—'}</dd>
              </div>
              <div>
                <dt>
                  <label htmlFor="username">{t('st.username')}</label>
                </dt>
                <dd>
                  <form
                    className={local.nameRow}
                    onSubmit={(e) => {
                      e.preventDefault()
                      submitUsername()
                    }}
                  >
                    <input
                      id="username"
                      className={styles.input}
                      maxLength={32}
                      autoComplete="nickname"
                      placeholder={t('st.usernamePlaceholder')}
                      value={usernameDraft}
                      onChange={(e) => setUsernameDraft(e.target.value)}
                    />
                    <button
                      type="submit"
                      className={`${styles.btn} ${styles.primary}`}
                      disabled={savingName || normalizeUsername(usernameDraft) === (savedUsername ?? '')}
                    >
                      {savingName && <span className={styles.spinner} aria-hidden="true" />}
                      {savingName ? t('settings.saving') : t('settings.save')}
                    </button>
                  </form>
                  {!savedUsername && !nameNotice && <p className={local.nameHint}>{t('st.usernameMissing')}</p>}
                  <NoticeLine notice={nameNotice} onClose={() => setNameNotice(null)} />
                </dd>
              </div>
              <div>
                <dt>{t('st.plan')}</dt>
                <dd>{t('dash.planRounds', { rounds: tier === 'subscribed' ? PAID_ROUNDS : FREE_ROUNDS })}</dd>
              </div>
            </dl>
            <div className={local.accountFoot}>
              <button type="button" className={`${styles.btn} ${styles.danger}`} onClick={() => signOutWithToast(t)}>
                {t('st.signOut')}
              </button>
              <nav className={local.legalLinks} aria-label="Legal">
                <Link className="link-wipe" to="/privacy">
                  {t('st.privacy')}
                </Link>
                <Link className="link-wipe" to="/terms">
                  {t('st.terms')}
                </Link>
              </nav>
            </div>
          </section>

          {/* API keys */}
          <section id="team" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('org.team')}</h2>
                <p className={styles.panelSub}>{t('org.teamSub')}</p>
              </div>
            </div>
            <TeamSettings />
          </section>

          <section id="brand" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('brand.title')}</h2>
                <p className={styles.panelSub}>{t('brand.sub')}</p>
              </div>
            </div>
            <BrandKitSettings />
          </section>

          <section id="email" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('em.title')}</h2>
                <p className={styles.panelSub}>{t('em.sub')}</p>
              </div>
            </div>
            <EmailSendingSettings />
          </section>

          <section id="billing" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('billing.title')}</h2>
                <p className={styles.panelSub}>{t('billing.sub')}</p>
              </div>
            </div>
            <BillingSettings />
          </section>

          {canManage && (
            <section id="usage" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('obs.title')}</h2>
                  <p className={styles.panelSub}>{t('obs.sub')}</p>
                </div>
              </div>
              <UsageStats />
            </section>
          )}

          {canManage && (
            <section id="api" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('api.title')}</h2>
                  <p className={styles.panelSub}>{t('api.sub')}</p>
                </div>
              </div>
              <ApiSettings />
            </section>
          )}

          {canManage && (
            <section id="audit" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
              <div className={styles.panelHead}>
                <div>
                  <h2>{t('audit.title')}</h2>
                  <p className={styles.panelSub}>{t('audit.sub')}</p>
                </div>
              </div>
              <AuditLog />
            </section>
          )}

          <section id="keys" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('st.keysTitle')}</h2>
                <p className={styles.panelSub}>{t('settings.subtitle')}</p>
              </div>
            </div>
            <p className={local.security}>
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <rect x="5" y="11" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="2" />
                <path d="M8 11V8a4 4 0 0 1 8 0v3" stroke="currentColor" strokeWidth="2" />
              </svg>
              {t('st.securityNote')}
            </p>
            <div className={local.keys}>
              {CAPABILITIES.map((capability) => {
                const existing = keys[capability]
                return (
                  <article key={capability} className={local.key}>
                    <div className={local.keyHead}>
                      <span className={local.keyIcon}>
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          {KEY_ICONS[capability]}
                        </svg>
                      </span>
                      <div className={local.keyTitle}>
                        <strong>{t(`st.cap_${capability}`)}</strong>
                        <span>{t(`st.cap_${capability}_desc`)}</span>
                      </div>
                      {existing ? (
                        <span className={`${styles.pill} ${styles.pillDone}`}>
                          <span className={styles.pillDot} aria-hidden="true" />
                          {t('st.active')}
                        </span>
                      ) : (
                        <span className={styles.pill}>{t('settings.notSet')}</span>
                      )}
                    </div>
                    {existing && (
                      <p className={local.masked}>
                        <code>{existing.masked_key}</code>
                        <span>{t('st.updated', { time: fmt(existing.updated_at) })}</span>
                        <button type="button" className={local.removeKey} disabled={submitting === capability} onClick={() => removeKey(capability)}>
                          {t('st.removeKey')}
                        </button>
                      </p>
                    )}
                    <div className={styles.inputRow}>
                      <div className={local.secret}>
                        <input
                          type={reveal[capability] ? 'text' : 'password'}
                          className={styles.input}
                          placeholder={t('settings.keyPlaceholder')}
                          autoComplete="off"
                          spellCheck={false}
                          value={inputs[capability] ?? ''}
                          onChange={(e) => setInputs((prev) => ({ ...prev, [capability]: e.target.value }))}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') submit(capability)
                          }}
                        />
                        <button
                          type="button"
                          className={local.eye}
                          aria-label={reveal[capability] ? t('login.hidePassword') : t('login.showPassword')}
                          onClick={() => setReveal((prev) => ({ ...prev, [capability]: !prev[capability] }))}
                        >
                          <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" stroke="currentColor" strokeWidth="1.8" />
                            {reveal[capability] ? (
                              <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
                            ) : (
                              <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
                            )}
                          </svg>
                        </button>
                      </div>
                      <button
                        type="button"
                        className={`${styles.btn} ${styles.primary}`}
                        onClick={() => submit(capability)}
                        disabled={submitting === capability || !inputs[capability]?.trim()}
                      >
                        {submitting === capability && <span className={styles.spinner} aria-hidden="true" />}
                        {submitting === capability ? t('settings.saving') : t('settings.save')}
                      </button>
                    </div>
                  </article>
                )
              })}
            </div>
          </section>

          {/* Templates */}
          <section id="templates" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('st.navTemplates')}</h2>
                <p className={styles.panelSub}>{t('settings.templatesSubtitle')}</p>
              </div>
            </div>

            <div className={local.templates}>
              <div className={local.tplBlock}>
                <div className={local.tplHead}>
                  <strong>{t('settings.imageTemplateLabel')}</strong>
                  <span className={styles.pill}>{templates.image ? t('settings.set') : t('settings.notSet')}</span>
                </div>
                <label
                  className={`${local.drop} ${dragging ? local.dropActive : ''}`}
                  onDragOver={(e) => {
                    e.preventDefault()
                    setDragging(true)
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={onDrop}
                >
                  <input
                    type="file"
                    accept="image/*"
                    disabled={savingTemplate === 'image'}
                    onChange={(e) => e.target.files?.[0] && uploadImageTemplate(e.target.files[0])}
                  />
                  {templates.image?.image_base64 ? (
                    <img src={`data:image/png;base64,${templates.image.image_base64}`} alt={t('settings.imageTemplateLabel')} />
                  ) : (
                    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                      <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                  <span>
                    {savingTemplate === 'image' ? t('settings.saving') : templates.image ? t('st.replace') : t('st.dropHint')}
                  </span>
                </label>
              </div>

              <div className={local.tplBlock}>
                <div className={local.tplHead}>
                  <strong>{t('settings.emailTemplateLabel')}</strong>
                  <span className={styles.pill}>{templates.email ? t('settings.set') : t('settings.notSet')}</span>
                </div>
                <div className={local.editor}>
                  <textarea
                    className={`${styles.textarea} ${local.code}`}
                    rows={10}
                    spellCheck={false}
                    placeholder={t('settings.emailTemplatePlaceholder', { placeholder: '{{copy}}' })}
                    value={emailHtml}
                    onChange={(e) => setEmailHtml(e.target.value)}
                  />
                  <div className={local.preview}>
                    <span className={local.previewLabel}>{t('st.preview')}</span>
                    {previewDoc ? (
                      // Sandboxed: user HTML renders without scripts or same-origin access.
                      <iframe title={t('st.preview')} sandbox="" srcDoc={previewDoc} />
                    ) : (
                      <div className={`${styles.placeholder} ${local.previewEmpty}`}>
                        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                          <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
                          <path d="M3.5 6.5L12 13l8.5-6.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                        </svg>
                      </div>
                    )}
                  </div>
                </div>
                <div className={local.tplFoot}>
                  <button type="button" className={`${styles.btn} ${styles.primary}`} onClick={saveEmailTemplate} disabled={savingTemplate === 'email'}>
                    {savingTemplate === 'email' && <span className={styles.spinner} aria-hidden="true" />}
                    {savingTemplate === 'email' ? t('settings.saving') : t('settings.save')}
                  </button>
                </div>
              </div>
            </div>
          </section>

          <section id="privacy" className={`${styles.panel} ${local.section} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
            <div className={styles.panelHead}>
              <div>
                <h2>{t('privacy.title')}</h2>
                <p className={styles.panelSub}>{t('privacy.sub')}</p>
              </div>
            </div>
            <PrivacySettings />
          </section>
        </div>
      </div>
    </div>
  )
}
