// Resend's delivery events (delivered, bounced, complained) for one
// organisation's own Resend account, at /resend-webhook/{org_id}: installed by
// email-setup when the organisation connected. No JWT: each request is
// authenticated by its Svix signature, checked with that organisation's
// signing secret from Vault. Handling: ../_shared/resend_webhook.ts.
import { createClient } from 'jsr:@supabase/supabase-js@2'

import { handleWebhook } from '../_shared/resend_webhook.ts'

const db = createClient(Deno.env.get('SUPABASE_URL')!, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!)

Deno.serve(async (req) => {
  try {
    return await handleWebhook(req, {
      async secret(org) {
        const { data, error } = await db.rpc('email_webhook_secret', { p_org: org })
        if (error) throw error
        return data
      },
      async record(e) {
        const { data, error } = await db.rpc('record_email_event', {
          p_org: e.org, p_event_id: e.eventId, p_type: e.type, p_resend_id: e.emailId, p_bounce_type: e.bounceType,
        })
        if (error) throw error
        return data
      },
    })
  } catch (err) {
    // A 5xx makes Resend retry the event later; recording it is idempotent.
    console.error('resend-webhook failed:', err instanceof Error ? err.message : err)
    return new Response('try again', { status: 500 })
  }
})
