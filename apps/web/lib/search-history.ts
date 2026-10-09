/** Recent searches for visitors who are not signed in. Signed-in users' history
 * lives on the server (`/search/recent`); anonymous history stays in this
 * browser only and never leaves it. Short, capped, and clearable. */

export const RECENT_KEY = "livepitch.recent-searches.v1"
export const MAX_RECENT = 10
export const MAX_QUERY = 100

export function normalizeSearch(query: string): string {
  return query.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY)
}

function defaultStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage
  } catch {
    return null // blocked by browser settings
  }
}

export function readRecent(storage: Storage | null = defaultStorage()): string[] {
  if (!storage) return []
  try {
    const parsed: unknown = JSON.parse(storage.getItem(RECENT_KEY) ?? "[]")
    if (!Array.isArray(parsed)) return []
    return parsed.filter((q): q is string => typeof q === "string").slice(0, MAX_RECENT)
  } catch {
    return []
  }
}

function write(storage: Storage | null, queries: string[]): string[] {
  if (storage) {
    try {
      storage.setItem(RECENT_KEY, JSON.stringify(queries))
    } catch {
      // quota / private mode: history is a convenience, not a requirement
    }
  }
  return queries
}

/** Newest first, case-insensitively unique, capped. Ignores one-character queries. */
export function addRecent(query: string, storage: Storage | null = defaultStorage()): string[] {
  const clean = normalizeSearch(query)
  if (clean.length < 2) return readRecent(storage)
  const rest = readRecent(storage).filter((q) => q.toLowerCase() !== clean.toLowerCase())
  return write(storage, [clean, ...rest].slice(0, MAX_RECENT))
}

export function removeRecent(query: string, storage: Storage | null = defaultStorage()): string[] {
  const lowered = normalizeSearch(query).toLowerCase()
  return write(
    storage,
    readRecent(storage).filter((q) => q.toLowerCase() !== lowered),
  )
}

export function clearRecent(storage: Storage | null = defaultStorage()): string[] {
  if (storage) {
    try {
      storage.removeItem(RECENT_KEY)
    } catch {
      // ignore
    }
  }
  return []
}
