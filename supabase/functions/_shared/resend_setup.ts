// Connecting a brand's own Resend account (the email-setup Edge Function).
// Plain fetch against Resend's REST API, injected so it runs under Node for
// tests (supabase/functions/_shared/resend_setup.test.ts) and Deno in the function.
//
// The brand's full-access key is used only here, only during setup: to list
// its domains, install our webhook and create a sending-only key restricted to
// the chosen domain. Only that sending-only key (and the webhook's signing
// secret) is returned for storage; the full key is never kept.

const API = 'https://api.resend.com'
const EVENTS = ['email.delivered', 'email.bounced', 'email.complained', 'email.delivery_delayed']
export const SANDBOX_FROM = 'onboarding@resend.dev'

export type SetupCode = 'invalid_key' | 'needs_full_access' | 'domain_not_verified' | 'bad_from' | 'webhook_slot_taken'
  | 'sandbox_address' | 'resend_error'

export class SetupError extends Error {
  code: SetupCode
  constructor(code: SetupCode, message: string) {
    super(message)
    this.code = code
  }
}

export interface Domain { id: string; name: string; verified: boolean }

async function call(fetchFn: typeof fetch, key: string, method: string, path: string, body?: unknown) {
  const res = await fetchFn(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  return { ok: res.ok, status: res.status, data: data as Record<string, unknown> }
}

function messageOf(data: Record<string, unknown>) {
  return String(data.message ?? data.name ?? 'unknown error').slice(0, 300)
}

/** The account's domains (verified first) and how many webhooks it already has. */
export async function inspectAccount(key: string, fetchFn: typeof fetch = fetch) {
  const domains = await call(fetchFn, key, 'GET', '/domains')
  if (domains.status === 401) throw new SetupError('invalid_key', messageOf(domains.data))
  if (domains.status === 403) throw new SetupError('needs_full_access', messageOf(domains.data))
  if (!domains.ok) throw new SetupError('resend_error', messageOf(domains.data))
  const hooks = await call(fetchFn, key, 'GET', '/webhooks')
  const list = ((domains.data.data as { id: string; name: string; status: string }[]) ?? [])
    .map((d) => ({ id: d.id, name: d.name, verified: d.status === 'verified' }))
    .sort((a, b) => Number(b.verified) - Number(a.verified))
  return { domains: list, existingWebhooks: hooks.ok ? ((hooks.data.data as unknown[]) ?? []).length : 0 }
}

export interface ConnectInput {
  key: string
  mode: 'live' | 'sandbox'
  domainId?: string
  fromLocal: string // the part before @ (live only)
  sandboxTo?: string // the Resend account owner's own address (sandbox only)
  webhookUrl: string
}

export interface Connection {
  sendingKey: string
  webhookId: string
  webhookSecret: string
  fromEmail: string
  domain: string | null
  domainId: string | null
}

/** Set the account up for CampaignIQ; on any failure, remove what this call created. */
export async function connectAccount(input: ConnectInput, fetchFn: typeof fetch = fetch): Promise<Connection> {
  let domain: Domain | null = null
  let fromEmail = SANDBOX_FROM
  if (input.mode === 'live') {
    const local = input.fromLocal.trim().toLowerCase()
    if (!/^[a-z0-9._+-]{1,64}$/.test(local)) throw new SetupError('bad_from', 'the from address must be a plain mailbox name, like "hello"')
    const { domains } = await inspectAccount(input.key, fetchFn)
    domain = domains.find((d) => d.id === input.domainId) ?? null
    if (!domain?.verified) throw new SetupError('domain_not_verified', 'pick a domain that Resend shows as verified')
    fromEmail = `${local}@${domain.name}`
  }

  const created: { webhook?: string; key?: string } = {}
  const undo = async () => {
    if (created.webhook) await call(fetchFn, input.key, 'DELETE', `/webhooks/${created.webhook}`).catch(() => undefined)
    if (created.key) await call(fetchFn, input.key, 'DELETE', `/api-keys/${created.key}`).catch(() => undefined)
  }
  try {
    const hook = await call(fetchFn, input.key, 'POST', '/webhooks', { endpoint: input.webhookUrl, events: EVENTS })
    if (!hook.ok) {
      if (hook.status === 401) throw new SetupError('invalid_key', messageOf(hook.data))
      if (hook.status === 403) throw new SetupError('needs_full_access', messageOf(hook.data))
      throw new SetupError('webhook_slot_taken', messageOf(hook.data))
    }
    created.webhook = String(hook.data.id)

    const keyBody: Record<string, string> = { name: 'CampaignIQ sending', permission: 'sending_access' }
    if (domain) keyBody.domain_id = domain.id
    const key = await call(fetchFn, input.key, 'POST', '/api-keys', keyBody)
    if (!key.ok) throw new SetupError('resend_error', messageOf(key.data))
    created.key = String(key.data.id)
    const sendingKey = String(key.data.token)

    if (input.mode === 'sandbox') {
      // Resend's sandbox sender only delivers to the account owner: one test send proves the address.
      const test = await call(fetchFn, sendingKey, 'POST', '/emails', {
        from: `CampaignIQ <${SANDBOX_FROM}>`, to: [String(input.sandboxTo ?? '').trim().toLowerCase()],
        subject: 'CampaignIQ is connected (sandbox)',
        html: '<p>Your Resend account is connected to CampaignIQ in sandbox mode. Campaign emails will come to this address, labelled, until you verify a domain.</p>',
      })
      if (!test.ok) throw new SetupError('sandbox_address', messageOf(test.data))
    }
    return { sendingKey, webhookId: created.webhook, webhookSecret: String(hook.data.signing_secret), fromEmail,
      domain: domain?.name ?? null, domainId: domain?.id ?? null }
  } catch (err) {
    await undo()
    throw err
  }
}
