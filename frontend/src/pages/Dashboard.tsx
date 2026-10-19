import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { CAMPAIGN_LANGUAGES } from '../lib/languages'
import { supabase } from '../lib/supabaseClient'
import styles from '../styles/shell.module.css'
import type { Campaign } from '../lib/types'

export default function Dashboard() {
  const { t } = useTranslation()
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [loading, setLoading] = useState(true)

  const [idea, setIdea] = useState('')
  const [targetLanguage, setTargetLanguage] = useState('en')
  const [creating, setCreating] = useState(false)
  const [createMessage, setCreateMessage] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    const { data } = await supabase.from('campaigns').select('*').order('created_at', { ascending: false })
    setCampaigns((data as Campaign[]) ?? [])
    setLoading(false)
  }

  useEffect(() => {
    load()
  }, [])

  async function createCampaign() {
    if (!idea.trim()) return
    setCreating(true)
    setCreateMessage(null)

    const { error } = await supabase.functions.invoke('create-campaign', {
      body: { idea, target_language: targetLanguage },
    })

    setCreating(false)
    if (error) {
      setCreateMessage(`Failed to dispatch: ${error.message}`)
      return
    }
    setCreateMessage('Campaign creation started — it will appear below once feasibility scoring completes.')
    setIdea('')
  }

  return (
    <div className={`max-w-3xl mx-auto p-8 ${styles.shell}`}>
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl">{t('dashboard.title')}</h1>
        <button onClick={load} className={`text-sm ${styles.muted} hover:underline`}>
          {t('dashboard.refresh')}
        </button>
      </div>

      <div className={`${styles.card} p-4 mb-6 space-y-3`}>
        <h2 className="font-medium">{t('dashboard.createTitle')}</h2>
        <textarea
          placeholder={t('dashboard.ideaPlaceholder')}
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={2}
          className={styles.textarea}
        />
        <div className="flex gap-2 items-center">
          <label className={`text-sm ${styles.muted}`}>{t('dashboard.languageLabel')}</label>
          <select
            value={targetLanguage}
            onChange={(e) => setTargetLanguage(e.target.value)}
            className={`${styles.select} text-sm`}
          >
            {CAMPAIGN_LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
          <button
            onClick={createCampaign}
            disabled={creating || !idea.trim()}
            className={`ml-auto ${styles.btn} ${styles.btnPrimary}`}
          >
            {creating ? t('dashboard.creating') : t('dashboard.createSubmit')}
          </button>
        </div>
        {createMessage && <p className="text-sm" style={{ color: 'var(--mos-accent)' }}>{createMessage}</p>}
      </div>

      {loading && <p className={styles.muted}>{t('common.loading')}</p>}

      {!loading && campaigns.length === 0 && <p className={styles.muted}>{t('dashboard.empty')}</p>}

      <ul className="space-y-3">
        {campaigns.map((c) => (
          <li key={c.id} className={`${styles.card} ${styles.cardHover} p-4`}>
            <Link to={`/campaigns/${c.id}`} className="block">
              <div className="flex justify-between items-center">
                <span className="font-medium">{c.idea}</span>
                <span className={styles.badge}>{c.status}</span>
              </div>
              <div className={`text-sm ${styles.muted} mt-1`}>
                {c.domain_category} · {t('dashboard.feasibility')} {c.feasibility_score ?? '—'}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
