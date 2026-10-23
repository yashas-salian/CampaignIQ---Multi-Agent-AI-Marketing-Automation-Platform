import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import i18next from 'i18next'

import { roleCan, type Role } from './roles'
import { toastLoadError } from './notify'
import { supabase } from './supabaseClient'
import { useSession } from './useAuth'
import { OrgContext, type Org, type OrgState } from './useOrg'

/** Loads the signed-in user's organisations and remembers the active one. */
const storageKey = (userId: string) => `mos.activeOrg.${userId}`

function readStored(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export default function OrgProvider({ children }: { children: ReactNode }) {
  const { session } = useSession()
  const userId = session?.user.id ?? null
  const [orgs, setOrgs] = useState<Org[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    if (!userId) {
      setOrgs([])
      setLoading(false)
      return
    }
    const { data, error } = await supabase
      .from('memberships')
      .select('role, organizations(id, name, personal)')
      .eq('user_id', userId)
    if (toastLoadError(i18next.t, error, () => reload())) {
      setLoading(false)
      return
    }
    const list: Org[] = (data ?? [])
      .map((m) => {
        const o = m.organizations as unknown as { id: string; name: string; personal: boolean } | null
        return o ? { id: o.id, name: o.name, personal: o.personal, role: m.role as Role } : null
      })
      .filter((o): o is Org => o !== null)
      .sort((a, b) => Number(b.personal) - Number(a.personal) || a.name.localeCompare(b.name))
    setOrgs(list)
    setActiveId((current) => {
      const wanted = current ?? readStored(storageKey(userId))
      return list.some((o) => o.id === wanted) ? wanted : (list[0]?.id ?? null)
    })
    setLoading(false)
  }, [userId])

  useEffect(() => {
    setLoading(true)
    setActiveId(null)
    reload()
  }, [reload])

  const setActive = useCallback(
    (orgId: string) => {
      setActiveId(orgId)
      if (userId) {
        try {
          localStorage.setItem(storageKey(userId), orgId)
        } catch {
          // private mode: the choice just isn't remembered
        }
      }
    },
    [userId],
  )

  const value = useMemo<OrgState>(() => {
    const active = orgs.find((o) => o.id === activeId) ?? null
    return {
      orgs,
      active,
      loading,
      setActive,
      reload,
      can: (permission, orgId) => roleCan((orgId ? orgs.find((o) => o.id === orgId) : active)?.role, permission),
    }
  }, [orgs, activeId, loading, setActive, reload])

  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>
}
