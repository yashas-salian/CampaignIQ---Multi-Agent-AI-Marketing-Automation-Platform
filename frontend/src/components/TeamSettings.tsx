import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ROLES, roleCan, type Role } from '../lib/roles'
import { useOrg } from '../lib/useOrg'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'

interface Member {
  user_id: string
  role: Role
  email: string
  username: string | null
}

interface Invitation {
  id: string
  email: string
  role: Role
  expires_at: string
}

/**
 * Organisation members, roles and invitations. Every action is enforced in the
 * database (membership functions + RLS); controls are only hidden here when the
 * caller's role can't use them.
 */
export default function TeamSettings() {
  const { t } = useTranslation()
  const { session } = useSession()
  const { orgs, active, setActive, reload, can } = useOrg()
  const [members, setMembers] = useState<Member[]>([])
  const [invites, setInvites] = useState<Invitation[]>([])
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<Role>('marketer')
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [newOrg, setNewOrg] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const orgId = active?.id
  const manage = can('manage')
  const own = can('own')

  const load = useCallback(async () => {
    if (!orgId) return
    const [{ data: m }, { data: i }] = await Promise.all([
      supabase.rpc('org_members', { p_org: orgId }),
      manage
        ? supabase.from('invitations').select('id,email,role,expires_at').eq('org_id', orgId).is('accepted_at', null)
        : Promise.resolve({ data: [] as Invitation[] }),
    ])
    setMembers((m as Member[] | null) ?? [])
    setInvites((i as Invitation[] | null) ?? [])
  }, [orgId, manage])

  useEffect(() => {
    load()
  }, [load])

  async function run(action: () => PromiseLike<{ error: { message: string } | null }>) {
    setBusy(true)
    setError(null)
    const { error: err } = await action()
    if (err) setError(err.message)
    await Promise.all([load(), reload()])
    setBusy(false)
  }

  async function createOrg(e: FormEvent) {
    e.preventDefault()
    if (!newOrg.trim()) return
    setBusy(true)
    setError(null)
    const { data, error: err } = await supabase.rpc('create_organization', { p_name: newOrg.trim() })
    if (err) setError(err.message)
    else {
      setNewOrg('')
      await reload()
      setActive(data as string)
    }
    setBusy(false)
  }

  async function invite(e: FormEvent) {
    e.preventDefault()
    if (!orgId || !inviteEmail.trim()) return
    setBusy(true)
    setError(null)
    setInviteLink(null)
    const { data, error: err } = await supabase.rpc('create_invitation', {
      p_org: orgId,
      p_email: inviteEmail.trim(),
      p_role: inviteRole,
    })
    if (err) setError(err.message)
    else {
      setInviteLink(`${window.location.origin}/invite/${data as string}`)
      setInviteEmail('')
      await load()
    }
    setBusy(false)
  }

  if (!active) return null
  const assignable = ROLES.filter((r) => own || !['owner', 'admin'].includes(r))

  return (
    <div className={local.team}>
      <div className={local.orgRow}>
        <label className={styles.field}>
          <span>{t('org.current')}</span>
          <select className={styles.select} value={active.id} onChange={(e) => setActive(e.target.value)}>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.personal ? t('org.personal') : o.name} · {t(`org.role_${o.role}`)}
              </option>
            ))}
          </select>
        </label>
        <form className={local.inline} onSubmit={createOrg}>
          <label className={styles.field}>
            <span>{t('org.createLabel')}</span>
            <input className={styles.input} value={newOrg} maxLength={80} placeholder={t('org.createPlaceholder')} onChange={(e) => setNewOrg(e.target.value)} />
          </label>
          <button className={`${styles.btn} ${styles.ghost}`} disabled={busy || !newOrg.trim()}>
            {t('org.create')}
          </button>
        </form>
      </div>

      {active.personal ? (
        <p className={styles.muted}>{t('org.personalNote')}</p>
      ) : (
        <>
          <ul className={local.members}>
            {members.map((m) => {
              const self = m.user_id === session?.user.id
              const canEdit = manage && !self && (own || !['owner', 'admin'].includes(m.role))
              return (
                <li key={m.user_id} className={local.member}>
                  <div className={local.who}>
                    <strong>{m.username || m.email}</strong>
                    {m.username && <span className={styles.muted}>{m.email}</span>}
                  </div>
                  {canEdit ? (
                    <select
                      className={`${styles.select} ${local.roleSelect}`}
                      value={m.role}
                      disabled={busy}
                      aria-label={t('org.roleFor', { who: m.email })}
                      onChange={(e) => run(() => supabase.rpc('set_member_role', { p_org: active.id, p_user: m.user_id, p_role: e.target.value }))}
                    >
                      {assignable.map((r) => (
                        <option key={r} value={r}>
                          {t(`org.role_${r}`)}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className={styles.chip}>{t(`org.role_${m.role}`)}</span>
                  )}
                  {(canEdit || self) && (
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.danger} ${local.small}`}
                      disabled={busy}
                      onClick={() => run(() => supabase.rpc('remove_member', { p_org: active.id, p_user: m.user_id }))}
                    >
                      {self ? t('org.leave') : t('org.remove')}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>

          {manage && (
            <form className={local.inviteForm} onSubmit={invite}>
              <label className={styles.field}>
                <span>{t('org.inviteEmail')}</span>
                <input className={styles.input} type="email" required value={inviteEmail} onChange={(e) => setInviteEmail(e.target.value)} />
              </label>
              <label className={styles.field}>
                <span>{t('org.inviteRole')}</span>
                <select className={styles.select} value={inviteRole} onChange={(e) => setInviteRole(e.target.value as Role)}>
                  {assignable
                    .filter((r) => r !== 'owner')
                    .map((r) => (
                      <option key={r} value={r}>
                        {t(`org.role_${r}`)}
                      </option>
                    ))}
                </select>
              </label>
              <button className={`${styles.btn} ${styles.primary}`} disabled={busy}>
                {t('org.invite')}
              </button>
            </form>
          )}

          {inviteLink && (
            <div className={local.link}>
              <p className={styles.muted}>{t('org.inviteLinkNote')}</p>
              <div className={local.inline}>
                <input className={styles.input} readOnly value={inviteLink} onFocus={(e) => e.target.select()} aria-label={t('org.inviteLink')} />
                <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => navigator.clipboard?.writeText(inviteLink)}>
                  {t('org.copy')}
                </button>
              </div>
            </div>
          )}

          {manage && invites.length > 0 && (
            <div>
              <h3 className={local.subhead}>{t('org.pending')}</h3>
              <ul className={local.members}>
                {invites.map((i) => (
                  <li key={i.id} className={local.member}>
                    <div className={local.who}>
                      <strong>{i.email}</strong>
                      <span className={styles.muted}>{t('org.expires', { date: new Date(i.expires_at).toLocaleDateString() })}</span>
                    </div>
                    <span className={styles.chip}>{t(`org.role_${i.role}`)}</span>
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.danger} ${local.small}`}
                      disabled={busy}
                      onClick={() => run(() => supabase.from('invitations').delete().eq('id', i.id))}
                    >
                      {t('org.revoke')}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {!roleCan(active.role, 'create') && <p className={styles.muted}>{t('org.readOnlyNote', { role: t(`org.role_${active.role}`) })}</p>}
      {error && (
        <p className={local.error} role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
