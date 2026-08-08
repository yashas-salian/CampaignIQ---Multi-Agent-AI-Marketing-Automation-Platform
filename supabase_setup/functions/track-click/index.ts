// Paste this into Supabase Dashboard -> Edge Functions -> Create a new function
// named "track-click", then Deploy. SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
// are injected automatically into every deployed Edge Function's environment.
import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  const params = new URL(req.url).searchParams;
  const destinationUrl = params.get("url");
  const campaignId = params.get("campaign_id");
  const roundId = params.get("round_id");
  const channel = params.get("channel") ?? "email";

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

  return Response.redirect(destinationUrl, 302);
});
