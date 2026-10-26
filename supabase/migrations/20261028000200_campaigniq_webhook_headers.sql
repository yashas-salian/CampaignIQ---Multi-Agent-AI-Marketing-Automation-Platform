-- The product is now called CampaignIQ.
-- New API keys start with "ciq_" (keys issued as "mos_" keep working: the API accepts both).
-- Outgoing webhooks carry X-CampaignIQ-*
-- headers (Event, Delivery, Signature) and identify themselves as
-- CampaignIQ-Webhooks/1. The signature itself is unchanged:
-- sha256=<HMAC-SHA256(secret, raw body)>. src/scheduler/webhooks.py (retries)
-- sends the same headers. During the transition the old X-MarketingOS-* headers
-- are sent too, with the same values, so existing receivers keep working.
create or replace function public.send_webhook(p_delivery bigint)
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  d public.webhook_deliveries;
  w public.webhooks;
  body text;
  signature text;
  request_id bigint;
begin
  select * into d from public.webhook_deliveries where id = p_delivery;
  select * into w from public.webhooks where id = d.webhook_id;
  body := d.payload::text;
  signature := 'sha256=' || encode(extensions.hmac(body, w.secret, 'sha256'), 'hex');
  select net.http_post(
    url := w.url,
    body := d.payload,
    headers := jsonb_build_object(
      'Content-Type', 'application/json',
      'User-Agent', 'CampaignIQ-Webhooks/1',
      'X-CampaignIQ-Event', d.event,
      'X-CampaignIQ-Delivery', d.id::text,
      'X-CampaignIQ-Signature', signature,
      'X-MarketingOS-Event', d.event,
      'X-MarketingOS-Delivery', d.id::text,
      'X-MarketingOS-Signature', signature
    ),
    timeout_milliseconds := 5000
  ) into request_id;
  update public.webhook_deliveries set net_request_id = request_id, updated_at = now() where id = d.id;
end;
$$;

create or replace function public.create_api_key(p_org uuid, p_name text, p_scopes text[] default '{read}')
returns text
language plpgsql security definer set search_path = ''
as $$
declare raw text := 'ciq_' || encode(extensions.gen_random_bytes(24), 'hex');
begin
  if not public.org_can(p_org, 'manage') then raise exception 'only owners and admins can create API keys'; end if;
  insert into public.api_keys (org_id, name, prefix, key_hash, scopes, created_by)
  values (p_org, trim(p_name), left(raw, 12), encode(extensions.digest(raw, 'sha256'), 'hex'), p_scopes, auth.uid());
  perform public.audit(p_org, 'api_key.created', 'api_key', left(raw, 12), jsonb_build_object('name', trim(p_name), 'scopes', p_scopes));
  return raw;
end;
$$;
