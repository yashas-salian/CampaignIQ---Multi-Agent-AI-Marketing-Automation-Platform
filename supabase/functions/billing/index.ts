// Starts Stripe Checkout (upgrade to Pro) or opens the Stripe customer portal
// for an organisation. JWT verification ON; only the organisation's owners
// may change billing. Secrets: STRIPE_SECRET_KEY (sk_test_... in test mode),
// STRIPE_PRICE_PRO, and APP_BASE_URL (where Stripe sends people back).
import { createClient } from "jsr:@supabase/supabase-js@2";

import { stripe } from "../_shared/stripe.ts";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function handle(req: Request): Promise<Response> {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) return new Response("Missing Authorization header", { status: 401 });
  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const userClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: userData } = await userClient.auth.getUser();
  if (!userData?.user) return new Response("Invalid session", { status: 401 });

  const secretKey = Deno.env.get("STRIPE_SECRET_KEY");
  if (!secretKey) return json({ error: "Billing isn't configured yet (STRIPE_SECRET_KEY)." }, 503);
  const { action, org_id } = await req.json().catch(() => ({}));
  const { data: isOwner } = await userClient.rpc("org_can", { p_org: org_id, p_permission: "own" });
  if (!isOwner) return json({ error: "Only the organisation's owners can manage billing." }, 403);

  const admin = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: billing } = await admin.from("org_billing").select("stripe_customer_id").eq("org_id", org_id).maybeSingle();
  const appUrl = (Deno.env.get("APP_BASE_URL") ?? new URL(req.headers.get("Origin") ?? "http://localhost:5173").origin).replace(/\/$/, "");

  if (action === "checkout") {
    const price = Deno.env.get("STRIPE_PRICE_PRO");
    if (!price) return json({ error: "Billing isn't configured yet (STRIPE_PRICE_PRO)." }, 503);
    const session = await stripe("checkout/sessions", secretKey, {
      mode: "subscription",
      line_items: [{ price, quantity: 1 }],
      client_reference_id: org_id,
      metadata: { org_id },
      subscription_data: { metadata: { org_id } },
      ...(billing?.stripe_customer_id ? { customer: billing.stripe_customer_id } : { customer_email: userData.user.email }),
      success_url: `${appUrl}/settings?billing=success#billing`,
      cancel_url: `${appUrl}/settings?billing=cancelled#billing`,
      allow_promotion_codes: true,
    });
    return json({ url: session.url });
  }

  if (action === "portal") {
    if (!billing?.stripe_customer_id) return json({ error: "No billing account yet: upgrade first." }, 409);
    const portal = await stripe("billing_portal/sessions", secretKey, {
      customer: billing.stripe_customer_id,
      return_url: `${appUrl}/settings#billing`,
    });
    return json({ url: portal.url });
  }

  return json({ error: "action must be checkout or portal" }, 400);
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS_HEADERS });
  let res: Response;
  try {
    res = await handle(req);
  } catch (err) {
    res = json({ error: err instanceof Error ? err.message : String(err) }, 500);
  }
  const headers = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v);
  return new Response(res.body, { status: res.status, headers });
});
