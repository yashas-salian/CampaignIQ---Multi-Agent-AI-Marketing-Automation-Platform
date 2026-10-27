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
// src.graph.run_campaign fresh. It first writes the campaigns row itself
// (status 'created', "Starting up" in the app, no feasibility score yet), so the
// campaign shows the moment the user clicks Create; the worker fills that row
// in at feasibility (src/db/supabase_client.py create_campaign). The category
// is a placeholder until then.
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

  const { idea, target_language, email_to, org_id, ab_test, product_image_path, tagline, cta_url, template } = await req.json();
  if (!idea) {
    return new Response("Missing idea", { status: 400 });
  }
  // Every ad is built around the real product (src/tools/ad_templates.py), so
  // the photo is required. It must be one this user uploaded: the
  // product-photos bucket keeps each user's photos under their own id.
  if (typeof product_image_path !== "string" || !product_image_path) {
    return new Response("Missing product photo", { status: 400 });
  }
  if (!product_image_path.startsWith(`${userData.user.id}/`) || product_image_path.includes("..")) {
    return new Response("That product photo isn't yours", { status: 403 });
  }
  const cleanTagline = typeof tagline === "string" ? tagline.trim() : "";
  if (cleanTagline.length > 80) {
    return new Response("Tagline is longer than 80 characters", { status: 400 });
  }
  let cleanLink = "";
  if (typeof cta_url === "string" && cta_url.trim()) {
    try {
      const parsed = new URL(cta_url.trim());
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") throw new Error("scheme");
      cleanLink = parsed.toString();
    } catch {
      return new Response("The link must be a web address (https://…)", { status: 400 });
    }
  }
  // Optional: an ad template every round must use (src/tools/ad_templates.py ids).
  const adTemplate = typeof template === "string" ? template.trim() : "";
  if (adTemplate && !/^[a-z_]{1,40}$/.test(adTemplate)) {
    return new Response("Unknown ad template", { status: 400 });
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
  // Plan limits, checked before anything is written so the reason comes back
  // plainly; the insert below is where the database enforces them.
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

  // The row, written with the caller's JWT: row-level security checks the
  // "create" permission and the quota trigger the plan limits.
  const { data: created, error: insertError } = await userClient
    .from("campaigns")
    .insert({
      idea,
      user_id: userData.user.id,
      ...(org_id ? { org_id } : {}),
      domain_category: "other",
      status: "created",
      target_language: target_language || "en",
      ab_test: ab_test === true,
      product_image_path,
      product_tagline: cleanTagline || null,
      cta_url: cleanLink || null,
      ad_template: adTemplate || null,
    })
    .select("id")
    .single();
  if (insertError || !created) {
    const message = insertError?.message ?? "the campaign couldn't be saved";
    const limited = message.includes("usage limit");
    return new Response(JSON.stringify({ error: limited ? message.replace(/^usage limit:\s*/, "") : message }), {
      status: limited ? 429 : 400,
      headers: { "Content-Type": "application/json" },
    });
  }
  const campaignId = created.id as string;

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
          // With idea set, this is the row written above for the worker to fill in.
          campaign_id: campaignId,
          // Derived from the verified JWT, never trusted from the request
          // body -- same pattern as ownership checks in resume-campaign.
          user_id: userData.user.id,
          org_id: org_id || "",
          ab_test: ab_test === true,
          target_language: target_language || "en",
          email_to: email_to || "",
          product_image: product_image_path,
          tagline: cleanTagline,
          cta_url: cleanLink,
        },
      }),
    },
  );

  if (!dispatchResponse.ok) {
    const errText = await dispatchResponse.text();
    // No worker is coming: say so on the row instead of leaving it "Starting up".
    await userClient
      .from("campaigns")
      .update({ status: "failed", start_error: "The campaign couldn't be started. Please try again." })
      .eq("id", campaignId);
    return new Response(JSON.stringify({ error: errText }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ dispatched: true, campaign_id: campaignId }), {
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
