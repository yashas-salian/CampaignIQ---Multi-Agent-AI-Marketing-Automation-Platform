-- Multilingual campaigns: per-campaign target language for generated
-- content (copy, personas, feasibility rationale) and localized research
-- signals. See src/languages.py for the supported code catalog.

alter table campaigns add column if not exists target_language text not null default 'en';
