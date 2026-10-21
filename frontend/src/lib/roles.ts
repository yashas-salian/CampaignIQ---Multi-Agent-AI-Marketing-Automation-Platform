// Organisation roles and what they allow. The database enforces every rule
// (RLS + org_can()); the frontend mirrors them only to hide or disable
// controls a user can't use, so this must stay in sync with role_can() in
// supabase/migrations/*_organizations.sql.
export type Role = 'owner' | 'admin' | 'marketer' | 'approver' | 'viewer'
export type Permission = 'view' | 'create' | 'approve' | 'manage' | 'own'
export const ROLES: Role[] = ['owner', 'admin', 'marketer', 'approver', 'viewer']

const GRANTS: Record<Permission, Role[]> = {
  view: ['owner', 'admin', 'marketer', 'approver', 'viewer'],
  create: ['owner', 'admin', 'marketer'],
  approve: ['owner', 'admin', 'approver'],
  manage: ['owner', 'admin'],
  own: ['owner'],
}

export const roleCan = (role: Role | null | undefined, permission: Permission) => !!role && GRANTS[permission].includes(role)
