// Persona archetypes -> 3D figures in public/personas/<archetype>.webp.
// Mirrors ARCHETYPES and guess_archetype() in src/capabilities/audience.py:
// new personas carry the archetype the AI chose; older ones are guessed here
// from their name and demographics.
export const ARCHETYPES = [
  'teacher', 'doctor', 'nurse', 'student', 'developer', 'chef', 'athlete', 'parent', 'retiree',
  'professional', 'entrepreneur', 'designer', 'farmer', 'traveler', 'gamer', 'scientist',
  'tradesperson', 'finance', 'creator', 'general',
] as const
export type Archetype = (typeof ARCHETYPES)[number]

const HINTS: [Archetype, string[]][] = [
  ['nurse', ['nurse', 'nursing']],
  ['doctor', ['doctor', 'physician', 'surgeon', 'dentist', 'medical', 'clinician']],
  ['teacher', ['teacher', 'educator', 'professor', 'tutor', 'lecturer']],
  ['student', ['student', 'undergrad', 'college', 'university', 'school']],
  ['developer', ['developer', 'engineer', 'programmer', 'software', 'coder', 'devops']],
  ['chef', ['chef', 'cook', 'baker', 'restaurant', 'culinary']],
  ['athlete', ['athlete', 'runner', 'fitness', 'gym', 'yoga', 'sport', 'cyclist']],
  ['parent', ['parent', 'mother', 'father', 'mom', 'dad', 'mum']],
  ['retiree', ['retiree', 'retired', 'pensioner', 'senior', 'grandparent']],
  ['scientist', ['scientist', 'researcher', 'lab', 'biologist', 'chemist']],
  ['designer', ['designer', 'artist', 'creative', 'illustrator', 'architect']],
  ['farmer', ['farmer', 'agricultur', 'grower']],
  ['traveler', ['traveler', 'traveller', 'backpacker', 'tourist', 'nomad']],
  ['gamer', ['gamer', 'gaming', 'esports']],
  ['tradesperson', ['construction', 'electrician', 'plumber', 'mechanic', 'tradesperson', 'carpenter']],
  ['finance', ['finance', 'accountant', 'analyst', 'banker', 'investor']],
  ['creator', ['creator', 'influencer', 'youtuber', 'streamer', 'blogger']],
  ['entrepreneur', ['entrepreneur', 'founder', 'business owner', 'shop owner', 'freelancer', 'self-employed']],
  ['professional', ['professional', 'manager', 'executive', 'consultant', 'office', 'corporate']],
]

// Mirrors guess_gender() in audience.py: the AI's stated gender wins; older
// personas use the pronouns in their description. Never guessed from the name.
export type Gender = 'female' | 'male' | 'unspecified'
const FEMALE = /\b(she|her|hers|herself|woman|women|mother|mom|mum|wife|girl|grandmother)\b/g
const MALE = /\b(he|him|his|himself|man|men|father|dad|husband|boy|grandfather)\b/g

export function genderFor(gender: unknown, ...texts: unknown[]): Gender {
  const picked = typeof gender === 'string' ? gender.trim().toLowerCase() : ''
  if (picked === 'female' || picked === 'male') return picked
  const blob = texts.filter((t) => typeof t === 'string').join(' ').toLowerCase()
  const female = blob.match(FEMALE)?.length ?? 0
  const male = blob.match(MALE)?.length ?? 0
  return female > male ? 'female' : male > female ? 'male' : 'unspecified'
}

export function archetypeFor(archetype: unknown, ...texts: unknown[]): Archetype {
  const picked = typeof archetype === 'string' ? archetype.trim().toLowerCase() : ''
  if ((ARCHETYPES as readonly string[]).includes(picked) && picked !== 'general') return picked as Archetype
  const blob = texts.filter((t) => typeof t === 'string').join(' ').toLowerCase()
  return HINTS.find(([, words]) => words.some((w) => blob.includes(w)))?.[0] ?? 'general'
}
