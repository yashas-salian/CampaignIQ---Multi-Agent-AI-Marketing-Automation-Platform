// The campaign composer's product fields (components/ProductFields.tsx).
// Every ad is built around the real product (src/tools/ad_templates.py), so
// the photo is required; the tagline and link are optional.
export const PRODUCT_PHOTO_TYPES = ['image/png', 'image/jpeg', 'image/webp']
export const PRODUCT_PHOTO_MAX_BYTES = 5 * 1024 * 1024
export const TAGLINE_MAX = 80

/** True for an empty value or an http(s) address. */
export function isWebLink(value: string): boolean {
  if (!value.trim()) return true
  try {
    const url = new URL(value.trim())
    return url.protocol === 'https:' || url.protocol === 'http:'
  } catch {
    return false
  }
}
