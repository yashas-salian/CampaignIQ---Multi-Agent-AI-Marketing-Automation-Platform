import { useSession } from './useAuth'

export const CONTACT_EMAIL = 'safiya.khan@nonstopio.com'
export const REPO_URL = 'https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform'

/** Where log-in / sign-up calls to action should go for this visitor. */
export function useAuthTargets() {
  const { session, loading } = useSession()
  const authed = !loading && !!session
  return { authed, loginTo: authed ? '/dashboard' : '/login', signupTo: authed ? '/dashboard' : '/signup' }
}
