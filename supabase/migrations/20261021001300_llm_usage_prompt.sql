-- Which registered prompt (id@version, src/prompts) each LLM call used, so a
-- change in quality, tokens or failures can be traced to a prompt change.
alter table public.llm_usage add column if not exists prompt text;
create index if not exists llm_usage_prompt_idx on public.llm_usage (prompt, created_at desc);
