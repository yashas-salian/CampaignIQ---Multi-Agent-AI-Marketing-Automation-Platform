-- Persona archetype (teacher, doctor, student, ...): picks the 3D figure shown
-- on persona cards. Chosen by the persona prompt (audience.personas 1.1.0) from
-- the fixed list in src/capabilities/audience.py; older personas get a keyword
-- guess in the frontend.
alter table public.personas add column if not exists archetype text not null default 'general';
