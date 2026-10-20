// Paste into Supabase Dashboard -> Edge Functions -> Create a new function
// named "trigger-capability-run", then Deploy. Keep "Enforce JWT
// Verification" ON (the default).
//
// Requires two custom secrets (Edge Functions -> trigger-capability-run ->
// Secrets): GITHUB_REPO (e.g. "yashas-salian/CampaignIQ---Multi-Agent-AI-
// Marketing-Automation-Platform") and GITHUB_PAT (a GitHub Personal Access
// Token with the `actions:write` permission on that repo, used to call
// workflow_dispatch). SUPABASE_URL, SUPABASE_ANON_KEY, and
// SUPABASE_SERVICE_ROLE_KEY are injected automatically.
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

  const { capability, params } = await req.json();
  if (!capability) {
    return new Response("Missing capability", { status: 400 });
  }

  const serviceClient = createClient(supabaseUrl, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: runRow, error: insertError } = await serviceClient
    .from("capability_runs")
    .insert({ user_id: userData.user.id, capability, params: params ?? {}, status: "pending" })
    .select()
    .single();

  if (insertError || !runRow) {
    return new Response(JSON.stringify({ error: insertError?.message ?? "insert failed" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }

  const githubRepo = Deno.env.get("GITHUB_REPO")!;
  const githubToken = Deno.env.get("GITHUB_PAT")!;

  const dispatchResponse = await fetch(
    `https://api.github.com/repos/${githubRepo}/actions/workflows/capability-run.yml/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${githubToken}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        ref: "main",
        inputs: {
          run_id: runRow.id,
          user_id: userData.user.id,
          capability,
          params: JSON.stringify(params ?? {}),
        },
      }),
    },
  );

  if (!dispatchResponse.ok) {
    const errText = await dispatchResponse.text();
    await serviceClient.from("capability_runs").update({ status: "failed", error: errText }).eq("id", runRow.id);
    return new Response(JSON.stringify({ error: errText }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ run_id: runRow.id }), {
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
