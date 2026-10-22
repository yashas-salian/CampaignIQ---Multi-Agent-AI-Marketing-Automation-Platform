-- Persona gender (female / male / unspecified): picks the female or male
-- variant of the persona's 3D figure so it always matches the persona. Set by
-- the persona prompt (audience.personas 1.2.0); older personas fall back to
-- the pronouns in their description, else show initials.
alter table public.personas add column if not exists gender text not null default 'unspecified'
  check (gender in ('female', 'male', 'unspecified'));
