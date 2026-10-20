// Paste into Supabase Dashboard -> Edge Functions -> Create a new function
// named "resume-campaign", then Deploy. Keep "Enforce JWT Verification" ON.
//
// Reuses the same GITHUB_REPO + GITHUB_PAT secrets as trigger-capability-run
// (same repo, same PAT works for both workflows' workflow_dispatch calls).
// SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_SERVICE_ROLE_KEY are
// injected automatically.
import { createClient } from "jsr:@supabase/supabase-js@2";

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

  const { campaign_id } = await req.json();
  if (!campaign_id) {
    return new Response("Missing campaign_id", { status: 400 });
  }

  // service_role bypasses RLS, so ownership must be checked explicitly here
  // rather than relying on the query itself to deny access.
  const serviceClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: campaign, error: campaignError } = await serviceClient
    .from("campaigns")
    .select("id, user_id")
    .eq("id", campaign_id)
    .single();

  if (campaignError || !campaign || campaign.user_id !== userData.user.id) {
    return new Response("Campaign not found", { status: 404 });
  }

  const githubRepo = Deno.env.get("GITHUB_REPO")!;
  const githubToken = Deno.env.get("GITHUB_PAT")!;

  const dispatchResponse = await fetch(
    `https://api.github.com/repos/${githubRepo}/actions/workflows/campaign-loop.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubToken}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { campaign_id } }),
    },
  );

  if (!dispatchResponse.ok) {
    const errText = await dispatchResponse.text();
    return new Response(JSON.stringify({ error: errText }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ dispatched: true }), {
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
