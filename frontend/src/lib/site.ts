import { useSession } from './useAuth'

export const CONTACT_EMAILS = ['safiyakhan0225@gmail.com', 'yashassalian40@gmail.com']
/** For mailto: links, so a message reaches both. */
export const CONTACT_EMAIL = CONTACT_EMAILS.join(',')
/** For showing in text. */
export const CONTACT_EMAIL_TEXT = CONTACT_EMAILS.join(' or ')
export const REPO_URL = 'https://github.com/yashas-salian/CampaignIQ---Multi-Agent-AI-Marketing-Automation-Platform'

/** Where log-in / sign-up calls to action should go for this visitor. */
export function useAuthTargets() {
  const { session, loading } = useSession()
  const authed = !loading && !!session
  return { authed, loginTo: authed ? '/dashboard' : '/login', signupTo: authed ? '/dashboard' : '/signup' }
}

/** sessionStorage key: where to go after signing in (an invite link, a deep link into the app). */
export const NEXT_KEY = 'mos.next'
