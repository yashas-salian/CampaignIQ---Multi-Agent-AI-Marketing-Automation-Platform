-- An ad template the creator picked in the composer (optional). When set,
-- every round's ad, variant B included, uses that layout
-- (src/tools/ad_templates.py); the bandit still picks the copy tone. Unknown
-- ids are ignored by the worker, so this only checks the shape.
alter table public.campaigns add column if not exists ad_template text
  check (ad_template is null or ad_template ~ '^[a-z_]{1,40}$');
