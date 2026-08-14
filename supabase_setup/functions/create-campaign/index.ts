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

Deno.serve(async (req) => {
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

  const { idea, target_language, email_to } = await req.json();
  if (!idea) {
    return new Response("Missing idea", { status: 400 });
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
});
