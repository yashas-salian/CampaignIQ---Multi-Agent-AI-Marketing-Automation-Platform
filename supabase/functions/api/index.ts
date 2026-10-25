// MarketingOS public REST API (see docs/openapi.yaml). Deployed with JWT
// verification OFF (supabase/config.toml): callers authenticate with an
// organisation API key instead:  Authorization: Bearer mos_...
//
//   GET  /api/v1/campaigns               list (limit, status)            scope: read
//   GET  /api/v1/campaigns/{id}          one campaign + rounds + metrics scope: read
//   POST /api/v1/campaigns               start a campaign                scope: write
//   GET  /api/v1/usage                   plan, limits and usage          scope: read
//   GET  /api/v1/campaigns/{id}/decision            the decision engine's recommendation(s)  scope: read
//   POST /api/v1/decision-engine/evaluate           evaluate an idea (async, 202)            scope: write
//   GET  /api/v1/decision-engine/evaluations/{id}   that evaluation's status and result       scope: read
//   GET  /api/v1/campaigns/{id}/crash-tests          the campaign's crash-test reports        scope: read
//   POST /api/v1/campaigns/{id}/crash-tests          re-run on the round at Gate 2 (202)      scope: write
//   GET  /api/v1/campaigns/{id}/holds                circuit-breaker holds, paused or not      scope: read
//   POST /api/v1/campaigns/{id}/circuit-breaker/evaluate   check live conditions now (202)    scope: write
//   GET  /api/v1/campaigns/{id}/experiment           the proof-of-impact experiment and result scope: read
//   GET  /api/v1/experiments/{id}/impact             the impact read-out                      scope: read
//   POST /api/v1/conversions                         report a conversion (brand's site)       scope: write
//   GET  /api/v1/market-intelligence/competitors     tracked competitors and source health    scope: read
//   GET  /api/v1/market-intelligence/competitors/{id}/signals   observed moves, insights, forecasts  scope: read
//
// Keys are resolved with api_key_lookup() (service role), which also counts
// requests: 60 per minute per key. Every query is pinned to the key's org.
import { createClient } from "jsr:@supabase/supabase-js@2";

const RATE_LIMIT = 60;

function json(body: unknown, status = 200, extra: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...extra } });
}
const fail = (status: number, message: string) => json({ error: { status, message } }, status);

const EXPERIMENT_FIELDS = "id,campaign_id,hypothesis,primary_metric,design,assignment_unit,control_share,attribution_window_days," +
  "duration_days,min_units_per_arm,min_effect,policy_version,status,started_at,ends_at,analysis_at,result_status,result,analyzed_at,concluded_at";

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// Mirrors impact_api_view() in src/capabilities/impact.py.
// deno-lint-ignore no-explicit-any
function impactView(e: { result: any; primary_metric: string; analyzed_at: string | null }) {
  const r = e.result;
  if (!r) {
    return { status: "INCONCLUSIVE", primaryMetric: e.primary_metric, controlRate: null, treatmentRate: null, absoluteLift: null,
             confidenceOrCredibleInterval: null, reason: "NOT_ANALYZED_YET" };
  }
  const est = r.estimate ?? {};
  return {
    status: r.status, reason: r.reason, primaryMetric: r.primary_metric, controlRate: est.control_rate ?? null,
    treatmentRate: est.treatment_rate ?? null, absoluteLift: est.absolute_lift ?? null,
    confidenceOrCredibleInterval: est.interval ?? null, intervalMethod: "newcombe_hybrid_score_95",
    probabilityTreatmentBetter: est.prob_treatment_better ?? null, relativeLift: est.relative_lift ?? null,
    final: !!r.final, analyzedAt: r.analyzed_at ?? e.analyzed_at,
  };
}

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

  // GET /v1/campaigns/{id}/decision: latest recommendation first, then earlier ones (re-evaluations)
  const decisionOf = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})\/decision$/);
  if (req.method === "GET" && decisionOf) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data: campaign } = await admin.from("campaigns").select("id").eq("id", decisionOf[1]).eq("org_id", key.org_id).maybeSingle();
    if (!campaign) return fail(404, "Campaign not found");
    const { data, error } = await admin.from("campaign_decisions")
      .select("decision,opportunity_score,uncertainty,reason_codes,factors,hard_blocks,review_flags,constraints,reevaluate,baseline,policy_version,trigger,outcome,created_at")
      .eq("campaign_id", campaign.id).order("created_at", { ascending: false });
    if (error) return fail(500, error.message);
    if (!data?.length) return fail(404, "No decision for this campaign yet (it's decided before Gate 1)");
    return json({ data: { latest: { ...data[0], requires_human_approval: true }, history: data.slice(1) } });
  }

  // /v1/campaigns/{id}/crash-tests: GET the reports (newest first), POST to re-run on the round now at Gate 2
  const crash = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})\/crash-tests$/);
  if (crash && (req.method === "GET" || req.method === "POST")) {
    if (!can(req.method === "GET" ? "read" : "write")) return fail(403, `This key lacks the ${req.method === "GET" ? "read" : "write"} scope`);
    const { data: campaign } = await admin.from("campaigns").select("id,status,current_round").eq("id", crash[1]).eq("org_id", key.org_id).maybeSingle();
    if (!campaign) return fail(404, "Campaign not found");
    if (req.method === "GET") {
      const { data, error } = await admin.from("crash_tests")
        .select("id,round_number,trigger,scenario_set,rules_version,status,risk,revised_risk,report,applied_at,created_at")
        .eq("campaign_id", campaign.id).order("created_at", { ascending: false });
      if (error) return fail(500, error.message);
      return json({ data: (data ?? []).map((r) => ({ ...r, simulation_only: true })) });
    }
    if (campaign.status !== "awaiting_gate_2") return fail(409, "A crash test can be re-run only while the round waits at Gate 2");
    if (!key.created_by) return fail(409, "The user who created this key no longer exists; create a new key");
    const params = { campaign_id: campaign.id, round: campaign.current_round };
    const { data: run, error: runError } = await admin.from("capability_runs")
      .insert({ user_id: key.created_by, capability: "crash_test", params, status: "pending" }).select("id").single();
    if (runError || !run) return fail(runError?.message?.startsWith("usage limit") ? 429 : 500, runError?.message ?? "could not queue");
    const dispatch = await fetch(
      `https://api.github.com/repos/${Deno.env.get("GITHUB_REPO")}/actions/workflows/capability-run.yml/dispatches`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("GITHUB_PAT")}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { run_id: run.id, user_id: key.created_by, capability: "crash_test", params: JSON.stringify(params) } }),
      },
    );
    if (!dispatch.ok) {
      await admin.from("capability_runs").update({ status: "failed", error: "dispatch failed" }).eq("id", run.id);
      return fail(502, `Could not start the crash test: ${await dispatch.text()}`);
    }
    return json({ data: { run_id: run.id, status: "pending", note: "The new report appears in GET /v1/campaigns/{id}/crash-tests in a minute or two." } }, 202);
  }

  // GET /v1/campaigns/{id}/holds: the circuit breaker's holds, active first
  const holdsOf = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})\/holds$/);
  if (req.method === "GET" && holdsOf) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data: campaign } = await admin.from("campaigns").select("id,paused_at").eq("id", holdsOf[1]).eq("org_id", key.org_id).maybeSingle();
    if (!campaign) return fail(404, "Campaign not found");
    const { data, error } = await admin.from("campaign_holds")
      .select("id,channel,trigger,severity,status,detail,evidence,signal_at,created_at,resolved_at,resolution_note")
      .eq("campaign_id", campaign.id).order("created_at", { ascending: false });
    if (error) return fail(500, error.message);
    return json({ data: { paused: !!campaign.paused_at, paused_at: campaign.paused_at, holds: data } });
  }

  // POST /v1/campaigns/{id}/circuit-breaker/evaluate: check the live conditions now (async)
  const evaluateBreaker = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})\/circuit-breaker\/evaluate$/);
  if (req.method === "POST" && evaluateBreaker) {
    if (!can("write")) return fail(403, "This key lacks the write scope");
    if (!key.created_by) return fail(409, "The user who created this key no longer exists; create a new key");
    const { data: campaign } = await admin.from("campaigns").select("id").eq("id", evaluateBreaker[1]).eq("org_id", key.org_id).maybeSingle();
    if (!campaign) return fail(404, "Campaign not found");
    const params = { campaign_id: campaign.id };
    const { data: run, error: runError } = await admin.from("capability_runs")
      .insert({ user_id: key.created_by, capability: "circuit_breaker", params, status: "pending" }).select("id").single();
    if (runError || !run) return fail(runError?.message?.startsWith("usage limit") ? 429 : 500, runError?.message ?? "could not queue");
    const dispatch = await fetch(
      `https://api.github.com/repos/${Deno.env.get("GITHUB_REPO")}/actions/workflows/capability-run.yml/dispatches`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("GITHUB_PAT")}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { run_id: run.id, user_id: key.created_by, capability: "circuit_breaker", params: JSON.stringify(params) } }),
      },
    );
    if (!dispatch.ok) {
      await admin.from("capability_runs").update({ status: "failed", error: "dispatch failed" }).eq("id", run.id);
      return fail(502, `Could not start the check: ${await dispatch.text()}`);
    }
    return json({ data: { run_id: run.id, status: "pending", note: "Results appear in GET /v1/campaigns/{id}/holds." } }, 202);
  }

  // POST /v1/decision-engine/evaluate: research + personas + decision, without starting a campaign
  if (req.method === "POST" && path === "/v1/decision-engine/evaluate") {
    if (!can("write")) return fail(403, "This key lacks the write scope");
    if (!key.created_by) return fail(409, "The user who created this key no longer exists; create a new key");
    const body = await req.json().catch(() => null);
    const idea = typeof body?.idea === "string" ? body.idea.trim() : "";
    if (idea.length < 5 || idea.length > 2000) return fail(400, "idea must be 5-2000 characters");
    const params: Record<string, string> = { idea, target_language: typeof body?.target_language === "string" ? body.target_language : "en" };
    if (typeof body?.cta_url === "string" && body.cta_url.trim()) {
      try {
        const u = new URL(body.cta_url.trim());
        if (u.protocol !== "https:" && u.protocol !== "http:") throw new Error();
        params.cta_url = u.toString();
      } catch {
        return fail(400, "cta_url must be a web address");
      }
    }
    const { data: run, error: runError } = await admin.from("capability_runs")
      .insert({ user_id: key.created_by, capability: "decision", params, status: "pending" }).select("id").single();
    if (runError || !run) return fail(runError?.message?.startsWith("usage limit") ? 429 : 500, runError?.message ?? "could not queue");
    const dispatch = await fetch(
      `https://api.github.com/repos/${Deno.env.get("GITHUB_REPO")}/actions/workflows/capability-run.yml/dispatches`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${Deno.env.get("GITHUB_PAT")}`, Accept: "application/vnd.github+json", "Content-Type": "application/json" },
        body: JSON.stringify({ ref: "main", inputs: { run_id: run.id, user_id: key.created_by, capability: "decision", params: JSON.stringify(params) } }),
      },
    );
    if (!dispatch.ok) {
      await admin.from("capability_runs").update({ status: "failed", error: "dispatch failed" }).eq("id", run.id);
      return fail(502, `Could not start the evaluation: ${await dispatch.text()}`);
    }
    return json({ data: { evaluation_id: run.id, status: "pending", poll: `/v1/decision-engine/evaluations/${run.id}` } }, 202);
  }

  // GET /v1/decision-engine/evaluations/{id}
  const evaluation = path.match(/^\/v1\/decision-engine\/evaluations\/([0-9a-f-]{36})$/);
  if (req.method === "GET" && evaluation) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data } = await admin.from("capability_runs").select("id,status,result,error,created_at")
      .eq("id", evaluation[1]).eq("capability", "decision").eq("user_id", key.created_by).maybeSingle();
    if (!data) return fail(404, "Evaluation not found");
    return json({ data });
  }

  // GET /v1/campaigns/{id}/experiment: the declared design and the latest analysis
  const experimentOf = path.match(/^\/v1\/campaigns\/([0-9a-f-]{36})\/experiment$/);
  if (req.method === "GET" && experimentOf) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data } = await admin.from("experiments").select(EXPERIMENT_FIELDS)
      .eq("campaign_id", experimentOf[1]).eq("org_id", key.org_id).maybeSingle();
    if (!data) return fail(404, "No experiment for this campaign in this organisation");
    return json({ data });
  }

  // GET /v1/experiments/{id}/impact
  const impactOf = path.match(/^\/v1\/experiments\/([0-9a-f-]{36})\/impact$/);
  if (req.method === "GET" && impactOf) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data } = await admin.from("experiments").select("id,status,primary_metric,result,analyzed_at")
      .eq("id", impactOf[1]).eq("org_id", key.org_id).maybeSingle();
    if (!data) return fail(404, "Experiment not found");
    return json({ data: impactView(data) });
  }

  // POST /v1/conversions: the brand's site reports a conversion, matched by the
  // link token (ciq_t) or the person's email address (hashed here, never stored).
  if (req.method === "POST" && path === "/v1/conversions") {
    if (!can("write")) return fail(403, "This key lacks the write scope");
    const body = await req.json().catch(() => null);
    if (!body || typeof body !== "object") return fail(400, "Send a JSON body");
    const eventId = typeof body.event_id === "string" ? body.event_id.trim() : "";
    if (!eventId || eventId.length > 200) return fail(400, "event_id is required (your id for this conversion, 1-200 characters): retries with the same id count once");
    const token = typeof body.token === "string" && /^[0-9a-f]{32}$/.test(body.token) ? body.token : null;
    const email = typeof body.email === "string" && body.email.includes("@") ? body.email.trim().toLowerCase() : null;
    if (!token && !email) return fail(400, "Send token (the ciq_t link parameter) or email to say who converted");
    const occurred = body.occurred_at ? new Date(body.occurred_at) : new Date();
    if (Number.isNaN(occurred.getTime())) return fail(400, "occurred_at must be an ISO 8601 time");
    if (occurred.getTime() > Date.now() + 5 * 60_000) return fail(400, "occurred_at is in the future");
    const value = body.value === undefined || body.value === null ? null : Number(body.value);
    if (value !== null && (!Number.isFinite(value) || value < 0)) return fail(400, "value must be a number of at least 0");
    const currency = typeof body.currency === "string" ? body.currency.toUpperCase() : null;
    if (currency && !/^[A-Z]{3}$/.test(currency)) return fail(400, "currency must be a 3-letter code");

    let experimentQuery = admin.from("experiments").select("id,status").eq("org_id", key.org_id);
    if (typeof body.experiment_id === "string") experimentQuery = experimentQuery.eq("id", body.experiment_id);
    else if (typeof body.campaign_id === "string") experimentQuery = experimentQuery.eq("campaign_id", body.campaign_id);
    else return fail(400, "Send experiment_id or campaign_id");
    const { data: experiment } = await experimentQuery.maybeSingle();
    if (!experiment) return fail(404, "Experiment not found in this organisation");
    if (experiment.status === "declared") return fail(409, "The experiment hasn't started yet");

    const unitHash = email ? await sha256Hex(`${experiment.id}:${email}`) : null;
    const { data, error } = await admin.rpc("record_conversion", {
      p_experiment: experiment.id, p_external_id: eventId, p_occurred_at: occurred.toISOString(), p_token: token,
      p_unit_hash: unitHash, p_qualified: body.qualified === true, p_value: value, p_currency: currency,
    });
    if (error) return fail(500, error.message);
    const row = data?.[0] ?? {};
    return json({ data: { matched: !!row.matched, duplicate: !!row.duplicate, counted: !!row.matched && !row.duplicate } }, 202);
  }

  // GET /v1/market-intelligence/competitors
  if (req.method === "GET" && path === "/v1/market-intelligence/competitors") {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data, error } = await admin.from("competitors")
      .select("id,name,website,keywords,category_keyword,markets,created_at,competitor_sources(kind,locator,approved,status,last_ok_at,last_error)")
      .eq("org_id", key.org_id).is("archived_at", null).order("name");
    return error ? fail(500, error.message) : json({ data });
  }

  // GET /v1/market-intelligence/competitors/{id}/signals: what they did (observed), what we
  // might do (insight, with inferred intent labelled), the forecast, and each source's freshness.
  const signalsOf = path.match(/^\/v1\/market-intelligence\/competitors\/([0-9a-f-]{36})\/signals$/);
  if (req.method === "GET" && signalsOf) {
    if (!can("read")) return fail(403, "This key lacks the read scope");
    const { data: competitor } = await admin.from("competitors").select("id,name,category_keyword")
      .eq("id", signalsOf[1]).eq("org_id", key.org_id).maybeSingle();
    if (!competitor) return fail(404, "Competitor not found");
    const limit = Math.min(Math.max(Number(url.searchParams.get("limit") ?? 50), 1), 200);
    const [{ data: sources }, { data: events, error }, { data: insights }, { data: predictions }] = await Promise.all([
      admin.from("competitor_sources").select("kind,locator,approved,status,last_fetched_at,last_ok_at,last_error").eq("competitor_id", competitor.id),
      admin.from("competitor_events").select("id,kind,summary,observed,url,outlet,published_at,observed_at,reports,outlets,original_outlet,confidence")
        .eq("competitor_id", competitor.id).order("observed_at", { ascending: false }).limit(limit),
      admin.from("competitor_insights").select("event_id,recommendation,options,explanations,confidence,relevance,policy_version,status,note")
        .eq("competitor_id", competitor.id),
      admin.from("competitor_predictions").select("event_id,target,keyword,horizon_days,origin_week,predicted_change,interval_low,interval_high,interval_level,model_version,status,observed_change,inside_interval,materialized,resolve_after")
        .eq("competitor_id", competitor.id),
    ]);
    if (error) return fail(500, error.message);
    const byEvent = <T extends { event_id: string }>(rows: T[] | null) => new Map((rows ?? []).map((r) => [r.event_id, r]));
    const insightOf = byEvent(insights), predictionOf = byEvent(predictions);
    const limitations = (sources ?? []).filter((s) => s.approved && s.status !== "ok")
      .map((s) => ({ kind: s.kind, locator: s.locator, status: s.status, last_ok_at: s.last_ok_at, detail: s.last_error }));
    return json({
      data: {
        competitor, sources, limitations,
        signals: (events ?? []).map((e) => ({
          ...e, observed_or_inferred: "observed",
          insight: insightOf.get(e.id) ?? null, forecast: predictionOf.get(e.id) ?? null,
        })),
      },
    });
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
