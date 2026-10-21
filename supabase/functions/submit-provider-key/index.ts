// Deployed by .github/workflows/supabase-deploy.yml with JWT verification ON
// (supabase/config.toml): unlike track-click, this must only ever run for a
// genuinely logged-in user.
//
// The key goes straight into Supabase Vault through store_provider_key(), a
// service-role-only database function: it is never stored in plain text and
// never returned. SUPABASE_URL, SUPABASE_ANON_KEY and
// SUPABASE_SERVICE_ROLE_KEY are injected automatically; no custom secret.
import { createClient } from "jsr:@supabase/supabase-js@2";

const ALLOWED_CAPABILITIES = ["llm", "image", "judge"];

async function handle(req: Request): Promise<Response> {
  const authHeader = req.headers.get("Authorization");
  if (!authHeader) {
    return new Response("Missing Authorization header", { status: 401 });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const userClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_ANON_KEY")!, {
    global: { headers: { Authorization: authHeader } },
  });
  const { data: userData, error: userError } = await userClient.auth.getUser();
  if (userError || !userData.user) {
    return new Response("Invalid session", { status: 401 });
  }

  const { capability, api_key } = await req.json();
  if (!capability || !api_key) {
    return new Response("Missing capability or api_key", { status: 400 });
  }
  if (!ALLOWED_CAPABILITIES.includes(capability)) {
    return new Response(`capability must be one of: ${ALLOWED_CAPABILITIES.join(", ")}`, { status: 400 });
  }

  const serviceClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: maskedKey, error: storeError } = await serviceClient.rpc("store_provider_key", {
    p_user_id: userData.user.id,
    p_capability: capability,
    p_api_key: String(api_key).trim(),
  });

  if (storeError) {
    return new Response(JSON.stringify({ error: storeError.message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ masked_key: maskedKey }), {
    headers: { "Content-Type": "application/json" },
  });
}

// Browsers call this through supabase.functions.invoke() from the website's own
// origin, so it must answer the CORS preflight (an OPTIONS request that never
// carries the Authorization header) and tag every response. "*" is safe here:
// access is gated by the user's JWT bearer token, not by cookies.
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: CORS_HEADERS });
  }
  let res: Response;
  try {
    res = await handle(req);
  } catch (err) {
    // Without CORS headers the browser would hide this behind a CORS error.
    res = new Response(`Internal error: ${err instanceof Error ? err.message : String(err)}`, { status: 500 });
  }
  const headers = new Headers(res.headers);
  for (const [key, value] of Object.entries(CORS_HEADERS)) headers.set(key, value);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
});
