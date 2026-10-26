import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ROLES, roleCan, type Role } from '../lib/roles'
import { useOrg } from '../lib/useOrg'
import { supabase } from '../lib/supabaseClient'
import { useSession } from '../lib/useAuth'
import { copyWithToast, toastFailure, toastLoadError } from '../lib/notify'
import styles from '../styles/app.module.css'
import local from './TeamSettings.module.css'
import Select from './Select'
import { toast } from '../lib/toast'

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
  const [busy, setBusy] = useState(false)

  const orgId = active?.id
  const manage = can('manage')
  const own = can('own')

  const load = useCallback(async () => {
    if (!orgId) return
    const [{ data: m, error: membersError }, { data: i }] = await Promise.all([
      supabase.rpc('org_members', { p_org: orgId }),
      manage
        ? supabase.from('invitations').select('id,email,role,expires_at').eq('org_id', orgId).is('accepted_at', null)
        : Promise.resolve({ data: [] as Invitation[] }),
    ])
    if (toastLoadError(t, membersError, () => load())) return
    setMembers((m as Member[] | null) ?? [])
    setInvites((i as Invitation[] | null) ?? [])
  }, [orgId, manage, t])

  useEffect(() => {
    load()
  }, [load])

  // Every member/invite change: a success toast, or the failure.
  async function run(action: () => PromiseLike<{ error: { message: string } | null }>, done: string) {
    setBusy(true)
    const { error: err } = await action()
    if (!toastFailure(t, err)) toast.success(done)
    await Promise.all([load(), reload()])
    setBusy(false)
  }

  async function createOrg(e: FormEvent) {
    e.preventDefault()
    if (!newOrg.trim()) return
    setBusy(true)
    const name = newOrg.trim()
    const { data, error: err } = await supabase.rpc('create_organization', { p_name: name })
    if (!toastFailure(t, err)) {
      setNewOrg('')
      await reload()
      setActive(data as string)
      toast.success(t('toast.orgCreated', { name }))
    }
    setBusy(false)
  }

  async function invite(e: FormEvent) {
    e.preventDefault()
    if (!orgId || !inviteEmail.trim()) return
    setBusy(true)
    setInviteLink(null)
    const { data, error: err } = await supabase.rpc('create_invitation', {
      p_org: orgId,
      p_email: inviteEmail.trim(),
      p_role: inviteRole,
    })
    if (!toastFailure(t, err)) {
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
          <Select
            value={active.id}
            onChange={(orgId) => {
              setActive(orgId)
              const name = orgs.find((o) => o.id === orgId)?.name
              if (name) toast.info(t('toast.orgSwitched', { name }))
            }}
            aria-label={t('org.current')}
            options={orgs.map((o) => ({
              value: o.id,
              label: `${o.personal ? t('org.personal') : o.name} · ${t(`org.role_${o.role}`)}`,
            }))}
          />
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
                    <Select
                      className={local.roleSelect}
                      value={m.role}
                      disabled={busy}
                      aria-label={t('org.roleFor', { who: m.email })}
                      onChange={(role) =>
                        run(
                          () => supabase.rpc('set_member_role', { p_org: active.id, p_user: m.user_id, p_role: role }),
                          t('toast.roleChanged', { who: m.username || m.email, role: t(`org.role_${role}`) }),
                        )
                      }
                      options={assignable.map((r) => ({ value: r, label: t(`org.role_${r}`) }))}
                    />
                  ) : (
                    <span className={styles.chip}>{t(`org.role_${m.role}`)}</span>
                  )}
                  {(canEdit || self) && (
                    <button
                      type="button"
                      className={`${styles.btn} ${styles.danger} ${local.small}`}
                      disabled={busy}
                      onClick={() =>
                        run(
                          () => supabase.rpc('remove_member', { p_org: active.id, p_user: m.user_id }),
                          self ? t('toast.leftOrg', { name: active.name }) : t('toast.memberRemoved', { who: m.username || m.email }),
                        )
                      }
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
                <Select
                  value={inviteRole}
                  aria-label={t('org.inviteRole')}
                  onChange={(r) => setInviteRole(r as Role)}
                  options={assignable.filter((r) => r !== 'owner').map((r) => ({ value: r, label: t(`org.role_${r}`) }))}
                />
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
                <button type="button" className={`${styles.btn} ${styles.ghost}`} onClick={() => copyWithToast(t, inviteLink)}>
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
                      onClick={() => run(() => supabase.from('invitations').delete().eq('id', i.id), t('toast.inviteRevoked', { email: i.email }))}
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

      {manage && <ApprovalPolicy orgId={active.id} />}

      {!roleCan(active.role, 'create') && <p className={styles.muted}>{t('org.readOnlyNote', { role: t(`org.role_${active.role}`) })}</p>}
    </div>
  )
}

interface Policy {
  required_approvals: number
  forbid_self_approval: boolean
  approval_sla_hours: number | null
  slack_webhook_url: string | null
}

/** How gates are decided in this organisation (owners and admins). */
function ApprovalPolicy({ orgId }: { orgId: string }) {
  const { t } = useTranslation()
  const [policy, setPolicy] = useState<Policy>({ required_approvals: 1, forbid_self_approval: false, approval_sla_hours: null, slack_webhook_url: null })
  // Who hears about approvals: chosen approvers, or (none chosen) everyone who can approve.
  const [approvers, setApprovers] = useState<{ user_id: string; email: string; username: string | null; role: string }[]>([])
  const [notify, setNotify] = useState<string[]>([])
  // Saved ids of people who have since left or can no longer approve are dropped.
  const notifyNow = notify.filter((id) => approvers.some((a) => a.user_id === id))

  useEffect(() => {
    supabase.rpc('org_members', { p_org: orgId }).then(({ data }) => {
      setApprovers(((data as { user_id: string; email: string; username: string | null; role: string }[]) ?? [])
        .filter((m) => ['owner', 'admin', 'approver'].includes(m.role)))
    })
    supabase.from('org_settings').select('notify_user_ids').eq('org_id', orgId).maybeSingle()
      .then(({ data }) => setNotify((data as { notify_user_ids: string[] } | null)?.notify_user_ids ?? []))
  }, [orgId])

  useEffect(() => {
    supabase
      .from('org_settings')
      .select('required_approvals,forbid_self_approval,approval_sla_hours,slack_webhook_url')
      .eq('org_id', orgId)
      .maybeSingle()
      .then(({ data, error }) => {
        if (error) toastFailure(t, error)
        else if (data) setPolicy(data as Policy)
      })
  }, [orgId, t])

  async function save(e: FormEvent) {
    e.preventDefault()
    const { error } = await supabase
      .from('org_settings')
      .upsert({ org_id: orgId, ...policy, slack_webhook_url: policy.slack_webhook_url?.trim() || null, updated_at: new Date().toISOString() })
    if (toastFailure(t, error)) return
    const people = await supabase.rpc('set_notification_people', { p_org: orgId, p_users: notifyNow })
    if (!toastFailure(t, people.error)) toast.success(t('approvals.savedToast'))
  }

  return (
    <form className={local.policy} onSubmit={save}>
      <h3 className={local.subhead}>{t('approvals.policy')}</h3>
      <div className={local.policyGrid}>
        <label className={styles.field}>
          <span>{t('approvals.required')}</span>
          <Select
            value={policy.required_approvals}
            aria-label={t('approvals.required')}
            onChange={(n) => setPolicy({ ...policy, required_approvals: n })}
            options={[1, 2, 3, 4, 5].map((n) => ({ value: n, label: String(n) }))}
          />
        </label>
        <label className={styles.field}>
          <span>{t('approvals.sla')}</span>
          <input
            className={styles.input}
            type="number"
            min={1}
            max={720}
            placeholder={t('approvals.slaNone')}
            value={policy.approval_sla_hours ?? ''}
            onChange={(e) => setPolicy({ ...policy, approval_sla_hours: e.target.value ? Number(e.target.value) : null })}
          />
        </label>
      </div>
      <label className={local.check}>
        <input type="checkbox" checked={policy.forbid_self_approval} onChange={(e) => setPolicy({ ...policy, forbid_self_approval: e.target.checked })} />
        <span>{t('approvals.forbidSelf')}</span>
      </label>
      <fieldset className={local.notify} data-testid="notify-people">
        <legend>{t('approvals.notifyWho')}</legend>
        {approvers.map((m) => (
          <label key={m.user_id} className={local.check}>
            <input type="checkbox" checked={notify.includes(m.user_id)}
              onChange={(e) => setNotify((ids) => (e.target.checked ? [...ids, m.user_id] : ids.filter((x) => x !== m.user_id)))} />
            <span>{m.username || m.email} · {t(`org.role_${m.role}`)}</span>
          </label>
        ))}
        <small className={local.hint}>{notifyNow.length ? t('approvals.notifyChosen') : t('approvals.notifyAll')}</small>
      </fieldset>
      <label className={styles.field}>
        <span>{t('approvals.slack')}</span>
        <input
          className={styles.input}
          type="url"
          placeholder="https://hooks.slack.com/services/..."
          value={policy.slack_webhook_url ?? ''}
          onChange={(e) => setPolicy({ ...policy, slack_webhook_url: e.target.value })}
        />
      </label>
      <div className={local.inline}>
        <button className={`${styles.btn} ${styles.primary}`}>{t('approvals.save')}</button>
      </div>
    </form>
  )
}
