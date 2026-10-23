import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import { toastFailure, toastLoadError } from '../lib/notify'
import styles from '../styles/app.module.css'
import Select from './Select'
import local from './Collab.module.css'

interface Comment {
  id: string
  user_id: string
  round_number: number | null
  body: string
  created_at: string
}

/** Team discussion on a campaign. Live: new comments appear without a reload. */
export default function CampaignComments({ campaignId, orgId, rounds }: { campaignId: string; orgId: string; rounds: number[] }) {
  const { t, i18n } = useTranslation()
  const { session } = useSession()
  const [comments, setComments] = useState<Comment[]>([])
  const [people, setPeople] = useState<Record<string, string>>({})
  const [body, setBody] = useState('')
  const [round, setRound] = useState<string>('')

  const load = useCallback(async () => {
    const { data, error } = await supabase
      .from('campaign_comments')
      .select('id,user_id,round_number,body,created_at')
      .eq('campaign_id', campaignId)
      .order('created_at')
    if (toastLoadError(t, error, () => load())) return
    setComments((data as Comment[] | null) ?? [])
  }, [campaignId, t])

  useEffect(() => {
    load()
    supabase.rpc('org_members', { p_org: orgId }).then(({ data }) =>
      setPeople(Object.fromEntries(((data as { user_id: string; email: string; username: string | null }[] | null) ?? []).map((m) => [m.user_id, m.username || m.email]))),
    )
    const channel = supabase
      .channel(`comments-${campaignId}`)
      .on('postgres_changes', { event: '*', schema: 'public', table: 'campaign_comments', filter: `campaign_id=eq.${campaignId}` }, () => load())
      .subscribe()
    return () => {
      supabase.removeChannel(channel)
    }
  }, [campaignId, orgId, load])

  async function post(e: FormEvent) {
    e.preventDefault()
    if (!body.trim()) return
    const { error } = await supabase.from('campaign_comments').insert({ campaign_id: campaignId, body: body.trim(), round_number: round ? Number(round) : null })
    // A failed post keeps the text so nothing typed is lost.
    if (toastFailure(t, error)) return
    setBody('')
    load()
  }

  const when = new Intl.DateTimeFormat(i18n.language, { dateStyle: 'medium', timeStyle: 'short' })
  return (
    <div className={local.comments}>
      {comments.length === 0 && <p className={styles.muted}>{t('collab.noComments')}</p>}
      <ul>
        {comments.map((c) => (
          <li key={c.id}>
            <div className={local.commentHead}>
              <strong>{people[c.user_id] ?? c.user_id.slice(0, 8)}</strong>
              {c.round_number && <span className={styles.chip}>{t('collab.round', { n: c.round_number })}</span>}
              <time dateTime={c.created_at}>{when.format(new Date(c.created_at))}</time>
              {c.user_id === session?.user.id && (
                <button type="button" className={local.linkBtn} onClick={async () => {
                  const { error } = await supabase.from('campaign_comments').delete().eq('id', c.id)
                  toastFailure(t, error)
                  load()
                }}>
                  {t('collab.delete')}
                </button>
              )}
            </div>
            <p>{c.body}</p>
          </li>
        ))}
      </ul>
      <form onSubmit={post} className={local.commentForm}>
        <textarea className={styles.textarea} rows={2} maxLength={4000} value={body} onChange={(e) => setBody(e.target.value)} placeholder={t('collab.placeholder')} />
        <div className={local.commentActions}>
          <Select
            aria-label={t('collab.about')}
            value={round}
            onChange={setRound}
            options={[{ value: '', label: t('collab.whole') }, ...rounds.map((r) => ({ value: String(r), label: t('collab.round', { n: r }) }))]}
          />
          <button className={`${styles.btn} ${styles.primary}`} disabled={!body.trim()}>
            {t('collab.post')}
          </button>
        </div>
      </form>
    </div>
  )
}
