// Paste into Supabase Dashboard -> Edge Functions -> Create a new function
// named "submit-provider-key", then Deploy. Keep "Enforce JWT Verification"
// ON (the default) — unlike track-click, this function must only ever run
// for a genuinely logged-in user.
//
// Requires one custom secret (Edge Functions -> submit-provider-key ->
// Secrets, or project-wide secrets): SETTINGS_ENCRYPTION_KEY, matching the
// same value as the Python backend's .env entry exactly. SUPABASE_URL,
// SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY are injected automatically.
import { createClient } from "jsr:@supabase/supabase-js@2";

const ALLOWED_CAPABILITIES = ["llm", "image", "judge"];

function base64Decode(b64: string): Uint8Array {
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function base64Encode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

async function encryptKey(rawKey: string): Promise<string> {
  const keyBytes = base64Decode(Deno.env.get("SETTINGS_ENCRYPTION_KEY")!);
  const cryptoKey = await crypto.subtle.importKey("raw", keyBytes, "AES-GCM", false, ["encrypt"]);
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt({ name: "AES-GCM", iv: nonce }, cryptoKey, new TextEncoder().encode(rawKey)),
  );
  const combined = new Uint8Array(nonce.length + ciphertext.length);
  combined.set(nonce, 0);
  combined.set(ciphertext, nonce.length);
  return base64Encode(combined);
}

function maskKey(rawKey: string): string {
  return rawKey.length >= 4 ? `****${rawKey.slice(-4)}` : "****";
}

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

  const encryptedKey = await encryptKey(api_key);
  const maskedKey = maskKey(api_key);

  const serviceClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { error: upsertError } = await serviceClient.from("provider_keys").upsert(
    {
      user_id: userData.user.id,
      capability,
      encrypted_key: encryptedKey,
      masked_key: maskedKey,
      updated_at: new Date().toISOString(),
    },
    { onConflict: "user_id,capability" },
  );

  if (upsertError) {
    return new Response(JSON.stringify({ error: upsertError.message }), {
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
