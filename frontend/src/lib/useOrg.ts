import { createContext, useContext } from 'react'

import type { Permission, Role } from './roles'

export interface Org {
  id: string
  name: string
  personal: boolean
  role: Role
}

export interface OrgState {
  orgs: Org[]
  active: Org | null
  loading: boolean
  setActive: (orgId: string) => void
  /** Permission in a given org (default: the active one). */
  can: (permission: Permission, orgId?: string | null) => boolean
  reload: () => Promise<void>
}

export const OrgContext = createContext<OrgState | null>(null)

export function useOrg(): OrgState {
  const ctx = useContext(OrgContext)
  if (!ctx) throw new Error('useOrg must be used inside <OrgProvider>')
  return ctx
}
