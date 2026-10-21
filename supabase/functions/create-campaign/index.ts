// Paste into Supabase Dashboard -> Edge Functions -> Create a new function
// named "create-campaign", then Deploy. Keep "Enforce JWT Verification" ON.
//
// Reuses the same GITHUB_REPO + GITHUB_PAT secrets as trigger-capability-run
// and resume-campaign (same repo, same PAT works for all three workflows'
// workflow_dispatch calls). SUPABASE_URL and SUPABASE_ANON_KEY are injected
// automatically.
//
// Unlike resume-campaign (which resumes an existing checkpointed graph),
// this dispatches campaign-loop.yml's "idea" input path, which runs
// src.graph.run_campaign fresh -- there is no campaigns row yet at dispatch
// time (domain_category is NOT NULL and only gets set once feasibility_node
// runs inside the graph), so this never touches the campaigns table itself.
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

  const { idea, target_language, email_to, org_id } = await req.json();
  if (!idea) {
    return new Response("Missing idea", { status: 400 });
  }
  // Creating a campaign in an organisation needs the "create" permission there
  // (owner, admin or marketer), checked with the caller's own JWT.
  if (org_id) {
    const { data: allowed, error: permError } = await userClient.rpc("org_can", {
      p_org: org_id,
      p_permission: "create",
    });
    if (permError || !allowed) {
      return new Response("You can't create campaigns in this organisation", { status: 403 });
    }
  }
  // Plan limits, checked before dispatch: the campaign row (where the database
  // enforces them too) is only written after the first LLM calls.
  const orgForQuota = org_id || (await userClient.rpc("my_personal_org")).data;
  if (orgForQuota) {
    const { data: quotaError } = await userClient.rpc("campaign_quota_error", { p_org: orgForQuota });
    if (quotaError) {
      return new Response(JSON.stringify({ error: quotaError }), {
        status: 429,
        headers: { "Content-Type": "application/json" },
      });
    }
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
      body: JSON.stringify({
        ref: "main",
        inputs: {
          idea,
          // Derived from the verified JWT, never trusted from the request
          // body -- same pattern as ownership checks in resume-campaign.
          user_id: userData.user.id,
          org_id: org_id || "",
          target_language: target_language || "en",
          email_to: email_to || "",
        },
      }),
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
