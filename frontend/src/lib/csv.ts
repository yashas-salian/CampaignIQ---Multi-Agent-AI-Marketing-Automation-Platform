/**
 * A small CSV reader for contact imports (RFC 4180: quoted fields, "" inside
 * quotes, commas and line breaks inside quotes). Comma, semicolon or tab
 * separated, picked from the header line; a UTF-8 byte-order mark is dropped.
 */
export function parseCsv(text: string): string[][] {
  const src = text.replace(/^﻿/, '')
  const firstLine = src.slice(0, src.search(/\r?\n|$/))
  const sep = [',', ';', '\t'].reduce((best, s) => (count(firstLine, s) > count(firstLine, best) ? s : best), ',')
  const rows: string[][] = []
  let row: string[] = []
  let field = ''
  let quoted = false
  for (let i = 0; i < src.length; i++) {
    const c = src[i]
    if (quoted) {
      if (c === '"' && src[i + 1] === '"') {
        field += '"'
        i++
      } else if (c === '"') quoted = false
      else field += c
    } else if (c === '"' && field === '') quoted = true
    else if (c === sep) {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && src[i + 1] === '\n') i++
      row.push(field)
      rows.push(row)
      row = []
      field = ''
    } else field += c
  }
  if (field !== '' || row.length) {
    row.push(field)
    rows.push(row)
  }
  return rows.filter((r) => r.some((f) => f.trim() !== ''))
}

function count(s: string, ch: string) {
  return s.split(ch).length - 1
}

/** What each CSV column can become on a contact. */
export const CONTACT_FIELDS = ['email', 'first_name', 'name', 'tags', 'language', 'last_purchase_at', 'orders', 'products', 'country'] as const
export type ContactField = (typeof CONTACT_FIELDS)[number]

const HINTS: Record<ContactField, RegExp> = {
  email: /e-?mail/i,
  first_name: /^(first|given)[\s_-]*name$|^first$|^prénom$|^nombre$/i,
  name: /^(full[\s_-]*)?name$|^customer$/i,
  tags: /tags?|labels?|groups?|segments?/i,
  language: /lang/i,
  last_purchase_at: /(last|latest).*(order|purchase|bought)|purchase[\s_-]*date|order[\s_-]*date/i,
  orders: /^(orders?|order[\s_-]*count|total[\s_-]*orders|purchases)$/i,
  products: /products?|items?|skus?/i,
  country: /country|nation/i,
}

/** Guess which column holds which field from the header names (each column used once). */
export function guessMapping(headers: string[]): Partial<Record<ContactField, number>> {
  const map: Partial<Record<ContactField, number>> = {}
  const used = new Set<number>()
  for (const field of CONTACT_FIELDS) {
    const i = headers.findIndex((h, idx) => !used.has(idx) && HINTS[field].test(h.trim()))
    if (i >= 0) {
      map[field] = i
      used.add(i)
    }
  }
  return map
}

const split = (v: string) => v.split(/[;|,]/).map((x) => x.trim()).filter(Boolean)

/** One CSV row as the contact upsert_contacts() expects. */
export function rowToContact(row: string[], map: Partial<Record<ContactField, number>>) {
  const cell = (f: ContactField) => (map[f] === undefined ? '' : (row[map[f]!] ?? '').trim())
  const attributes: Record<string, unknown> = {}
  if (cell('last_purchase_at')) attributes.last_purchase_at = cell('last_purchase_at')
  if (cell('orders') && !Number.isNaN(Number(cell('orders')))) attributes.orders = Number(cell('orders'))
  if (cell('products')) attributes.products = split(cell('products'))
  if (cell('country')) attributes.country = cell('country')
  const contact: Record<string, unknown> = { email: cell('email') }
  if (cell('first_name')) contact.first_name = cell('first_name')
  if (cell('name')) contact.name = cell('name')
  if (cell('language')) contact.language = cell('language').slice(0, 2).toLowerCase()
  contact.tags = split(cell('tags')).map((t) => t.toLowerCase())
  contact.attributes = attributes
  return contact
}
