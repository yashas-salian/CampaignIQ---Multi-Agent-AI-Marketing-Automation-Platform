// Deletes the caller's account (GDPR erasure). Deployed with JWT verification
// ON (supabase/config.toml).
//
// 1. prepare_account_deletion(): refuses while the user is the last owner of a
//    team with other members; hands their team campaigns to another owner;
//    deletes organisations where they're the only member (incl. personal).
// 2. auth.admin.deleteUser(): every personal table cascades from auth.users.
// The body must be {"confirm": "DELETE"} so a stray request can't erase an account.
import { createClient } from "jsr:@supabase/supabase-js@2";

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
  const { data: userData, error: userError } = await userClient.auth.getUser();
  if (userError || !userData.user) return new Response("Invalid session", { status: 401 });

  const { confirm } = await req.json().catch(() => ({}));
  if (confirm !== "DELETE") return json({ error: 'Send {"confirm": "DELETE"} to delete your account.' }, 400);

  const admin = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { error: prepError } = await admin.rpc("prepare_account_deletion", { p_user: userData.user.id });
  if (prepError) return json({ error: prepError.message }, 409);

  const { error: deleteError } = await admin.auth.admin.deleteUser(userData.user.id);
  if (deleteError) return json({ error: deleteError.message }, 500);
  return json({ deleted: true });
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
    res = new Response(`Internal error: ${err instanceof Error ? err.message : String(err)}`, { status: 500 });
  }
  const headers = new Headers(res.headers);
  for (const [key, value] of Object.entries(CORS_HEADERS)) headers.set(key, value);
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
});
