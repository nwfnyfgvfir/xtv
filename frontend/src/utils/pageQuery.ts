import type { LocationQuery, LocationQueryRaw } from 'vue-router'

/** Default page size for media / actor lists (balance covers vs. requests). */
export const DEFAULT_PAGE_SIZE = 36

/** Parse 1-based page from route query; invalid / missing → 1. */
export function parsePage(query: LocationQuery | LocationQueryRaw, key = 'page'): number {
  const raw = query[key]
  const v = Array.isArray(raw) ? raw[0] : raw
  const n = Number(v)
  if (!Number.isFinite(n) || n < 1) return 1
  return Math.floor(n)
}

/**
 * Patch for route.query: omit page when 1 to keep URLs clean.
 * Usage: `router.replace({ query: { ...route.query, ...pageQueryPatch(page) } })`
 */
export function pageQueryPatch(page: number, key = 'page'): LocationQueryRaw {
  if (!page || page <= 1) return { [key]: undefined }
  return { [key]: String(page) }
}

/** Read a single string query param (first value if array). */
export function queryString(
  query: LocationQuery | LocationQueryRaw,
  key: string,
): string {
  const raw = query[key]
  const v = Array.isArray(raw) ? raw[0] : raw
  return typeof v === 'string' ? v : ''
}

export function scrollListTop() {
  if (typeof window === 'undefined') return
  window.scrollTo({ top: 0, behavior: 'smooth' })
}
