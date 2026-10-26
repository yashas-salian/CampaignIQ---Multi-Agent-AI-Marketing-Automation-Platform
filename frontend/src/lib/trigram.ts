// pg_trgm's similarity(), so the copy editor asks for a reason exactly when the
// database will require one (edit_round_copy: similarity below 0.5 = a material edit).
function trigrams(text: string): Set<string> {
  const out = new Set<string>()
  for (const word of text.toLowerCase().split(/[^\p{L}\p{N}]+/u).filter(Boolean)) {
    const padded = `  ${word} `
    for (let i = 0; i + 3 <= padded.length; i++) out.add(padded.slice(i, i + 3))
  }
  return out
}

export function trigramSimilarity(a: string, b: string): number {
  const ta = trigrams(a)
  const tb = trigrams(b)
  if (!ta.size && !tb.size) return 1
  let shared = 0
  for (const t of ta) if (tb.has(t)) shared++
  return shared / (ta.size + tb.size - shared)
}

export const MATERIAL_EDIT = 0.5
export const isMaterialEdit = (before: string, after: string) => before.trim() !== after.trim() && trigramSimilarity(before, after) < MATERIAL_EDIT
