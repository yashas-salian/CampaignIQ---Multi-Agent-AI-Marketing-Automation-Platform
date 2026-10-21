// Stripe → MarketingOS: keeps each organisation's plan in step with its
// subscription. JWT verification OFF (Stripe can't send a Supabase JWT); every
// request is authenticated by its Stripe-Signature instead.
// Secrets: STRIPE_WEBHOOK_SECRET (whsec_...), STRIPE_SECRET_KEY.
// Stripe Dashboard → Developers → Webhooks → endpoint
//   https://<project>.supabase.co/functions/v1/stripe-webhook
// events: checkout.session.completed, customer.subscription.created,
//         customer.subscription.updated, customer.subscription.deleted
import { createClient } from "jsr:@supabase/supabase-js@2";

import { stripe, verifyStripeSignature } from "../_shared/stripe.ts";

Deno.serve(async (req) => {
  if (req.method !== "POST") return new Response("POST only", { status: 405 });
  const body = await req.text();
  const ok = await verifyStripeSignature(body, req.headers.get("Stripe-Signature"), Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "");
  if (!ok) return new Response("Invalid signature", { status: 400 });

  const event = JSON.parse(body);
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const apply = (org: string, customer: string, subscription: string, status: string, periodEnd: number | null) =>
    admin.rpc("apply_billing", {
      p_org: org,
      p_customer: customer,
      p_subscription: subscription,
      p_status: status,
      p_period_end: periodEnd ? new Date(periodEnd * 1000).toISOString() : null,
    });

  try {
    if (event.type === "checkout.session.completed") {
      const session = event.data.object;
      const org = session.client_reference_id ?? session.metadata?.org_id;
      if (org && session.subscription) {
        const sub = await stripe(`subscriptions/${session.subscription}`, Deno.env.get("STRIPE_SECRET_KEY")!, undefined, "GET");
        const { error } = await apply(org, session.customer, sub.id, sub.status, sub.current_period_end ?? sub.items?.data?.[0]?.current_period_end ?? null);
        if (error) throw new Error(error.message);
      }
    } else if (event.type.startsWith("customer.subscription.")) {
      const sub = event.data.object;
      const org = sub.metadata?.org_id;
      if (org) {
        const status = event.type === "customer.subscription.deleted" ? "canceled" : sub.status;
        const { error } = await apply(org, sub.customer, sub.id, status, sub.current_period_end ?? sub.items?.data?.[0]?.current_period_end ?? null);
        if (error) throw new Error(error.message);
      }
    }
  } catch (err) {
    // 500 makes Stripe retry the event later.
    return new Response(`Error: ${err instanceof Error ? err.message : String(err)}`, { status: 500 });
  }
  return new Response(JSON.stringify({ received: true }), { headers: { "Content-Type": "application/json" } });
});
