// MarketingOS public REST API (see docs/openapi.yaml). Deployed with JWT
// verification OFF (supabase/config.toml): callers authenticate with an
// organisation API key instead:  Authorization: Bearer mos_...
//
//   GET  /api/v1/campaigns               list (limit, status)            scope: read
//   GET  /api/v1/campaigns/{id}          one campaign + rounds + metrics scope: read
//   POST /api/v1/campaigns               start a campaign                scope: write
//   GET  /api/v1/usage                   plan, limits and usage          scope: read
//
// Keys are resolved with api_key_lookup() (service role), which also counts
// requests: 60 per minute per key. Every query is pinned to the key's org.
import { createClient } from "jsr:@supabase/supabase-js@2";

const RATE_LIMIT = 60;

function json(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...extra } });
}
const fail = (status: number, message: string) => json({ error: { status, message } }, status);

async function handle(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const path = url.pathname.replace(/^.*?\/api(?=\/|$)/, "").replace(/\/+$/, "") || "/";
  const auth = req.headers.get("Authorization") ?? "";
  const raw = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  if (!raw.startsWith("mos_")) return fail(401, "Send an API key: Authorization: Bearer mos_...");

  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!);
  const { data: keys, error: keyError } = await admin.rpc("api_key_lookup", { p_raw: raw, p_limit: RATE_LIMIT });
  const key = keys?.[0];
  if (keyError || !key) return fail(401, "Invalid or revoked API key");
  if (key.rate_limited) return json({ error: { status: 429, message: `Rate limit: ${RATE_LIMIT} requests per minute` } }, 429, { "Retry-After": "60" });
  const can = (scope: string) => (key.scopes as string[]).includes(scope);

  // GET /v1/campaigns
  if (req.method === "GET" && path === "/v1/campaigns") {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 20), 1), 100);
    let query = admin.from("campaigns")
      .select("id,idea,domain_category,status,feasibility_score,current_round,max_rounds,target_language,ab_test,created_at,updated_at")
      .eq("org_id", key.org_id).order("created_at", { ascending: false }).limit(limit);
    const status = url.searchParams.get("status");
    if (status) query = query.eq("status", status);
    const { data, error } = await query;
    return error ? fail(500, error.message) : json({ data });
  }

  // GET /v1/campaigns/{id}
  const one = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})$/);
  if (req.method === "GET" && one) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data: campaign } = await admin.from("campaigns")
      .select("id,idea,domain_category,status,feasibility_score,feasibility_rationale,current_round,max_rounds,target_language,ab_test,campaign_summary,created_at,updated_at")
      .eq("id", one[1]).eq("org_id", key.org_id).maybeSingle();
    if (!campaign) return fail(404, "Campaign not found");
    const [{ data: rounds }, { data: metrics }] = await Promise.all([
      admin.from("iterations").select("round_number,copy_text,copy_text_b,image_prompt,preflight_score,image_style,copy_tone,created_at")
        .eq("campaign_id", campaign.id).order("round_number"),
      admin.from("metrics").select("round_number,channel,raw_metrics,reward,collected_at").eq("campaign_id", campaign.id).order("round_number"),
    ]);
    return json({ data: { ...campaign, rounds, metrics } });
  }

  // POST /v1/campaigns
  if (req.method === "POST" && path === "/v1/campaigns") {
    if (!can("write")) return fail(403, "This key lacks the write scope");
    const body = await req.json().catch(() => null);
    const idea = typeof body?.idea === "string" ? body.idea.trim() : "";
    if (idea.length < 5 || idea.length > 2000) return fail(400, "idea must be 5-2000 characters");
    const emailTo = Array.isArray(body?.email_to) ? body.email_to.filter((e: unknown) => typeof e === "string").slice(0, 500) : [];
    const { data: quotaError } = await admin.rpc("campaign_quota_reason", { p_org: key.org_id });
    if (quotaError) return fail(429, quotaError);
    if (!key.created_by) return fail(409, "The user who created this key no longer exists; create a new key");
    const dispatch = await fetch(
      `https://api.github.com/repos/${Deno.env.get("GITHUB_REPO")}/actions/workflows/campaign-loop.yml/dispatches`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("GITHUB_PAT")}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" },
        body: JSON.stringify({
          ref: "main",
          inputs: {
            idea,
            user_id: key.created_by,
            org_id: key.org_id,
            target_language: typeof body?.target_language === "string" ? body.target_language : "en",
            email_to: emailTo.join(","),
            ab_test: body?.ab_test === true,
          },
        }),
      },
    );
    if (!dispatch.ok) return fail(502, `Could not start the run: ${await dispatch.text()}`);
    return json({ data: { accepted: true, note: "The campaign appears in GET /v1/campaigns within a minute or two." } }, 202);
  }

  // GET /v1/usage
  if (req.method === "GET" && path === "/v1/usage") {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data } = await admin.rpc("org_usage", { p_org: key.org_id });
    return json({ data });
  }

  return fail(404, `No route for ${req.method} ${path}`);
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS_HEADERS });
  let res: Response;
  try {
    res = await handle(req);
  } catch (err) {
    res = fail(500, `Internal error: ${err instanceof Error ? err.message : String(err)}`);
  }
  const headers = new Headers(res.headers);
  for (const [k, v] of Object.entries(CORS_HEADERS)) headers.set(k, v);
  return new Response(res.body, { status: res.status, headers });
});
