// Paste this into Supabase Dashboard -> Edge Functions -> Create a new function
// named "track-click", then Deploy. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
// are injected automatically into every deployed Edge Function's environment.
import { createClient } from "jsr:@supabase/supabase-js@2";

// A proof-of-impact link carries the recipient's experiment token (`t`): the
// click is credited to their unit, and the token goes on to the brand's site
// as `ciq_t` so a later conversion postback can say who converted.
const TOKEN = /^[0-9a-f]{32}$/;

Deno.serve(async (req) => {
  const params = new URL(req.url).searchParams;
  const destinationUrl = params.get("url");
  const campaignId = params.get("campaign_id");
  const roundId = params.get("round_id");
  const channel = params.get("channel") ?? "email";
  const token = params.get("t");

  if (!destinationUrl || !campaignId || !roundId) {
    return new Response("Missing required query params: url, campaign_id, round_id", { status: 400 });
  }

  const supabase = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  await supabase.from("click_log").insert({
    campaign_id: campaignId,
    round_id: Number(roundId),
    channel,
    destination_url: destinationUrl,
  });

  let target = destinationUrl;
  if (token && TOKEN.test(token)) {
    // Never block the redirect on the experiment write.
    const { error } = await supabase.rpc("record_click", { p_token: token, p_round: Number(roundId) });
    if (error) console.warn("record_click failed:", error.message);
    try {
      const url = new URL(destinationUrl);
      url.searchParams.set("ciq_t", token);
      target = url.toString();
    } catch {
      // not a parseable URL: redirect as given
    }
  }
  return Response.redirect(target, 302);
});
