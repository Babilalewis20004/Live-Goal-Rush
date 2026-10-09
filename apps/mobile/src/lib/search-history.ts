import * as SecureStore from "expo-secure-store"

// Recent searches for people who are not signed in. Signed-in users' history
// lives on the server (`/search/recent`). This stays on the device: short,
// capped, and clearable. (expo-secure-store is already a dependency and holds
// a few short strings fine; no extra storage package was added for this.)

export const RECENT_KEY = "livepitch.recent_searches"
export const MAX_RECENT = 10
export const MAX_QUERY = 100

export function normalizeSearch(query: string): string {
  return query.replace(/\s+/g, " ").trim().slice(0, MAX_QUERY)
}

/** Newest first, case-insensitively unique, capped. One-character queries are ignored. */
export function withRecent(list: string[], query: string): string[] {
  const clean = normalizeSearch(query)
  if (clean.length < 2) return list
  return [clean, ...list.filter((q) => q.toLowerCase() !== clean.toLowerCase())].slice(0, MAX_RECENT)
}

export function withoutRecent(list: string[], query: string): string[] {
  const lowered = normalizeSearch(query).toLowerCase()
  return list.filter((q) => q.toLowerCase() !== lowered)
}

export function parseRecent(raw: string | null): string[] {
  if (!raw) return []
  try {
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((q): q is string => typeof q === "string").slice(0, MAX_RECENT)
  } catch {
    return []
  }
}

export async function readRecent(): Promise<string[]> {
  try {
    return parseRecent(await SecureStore.getItemAsync(RECENT_KEY))
  } catch {
    return []
  }
}

export async function writeRecent(list: string[]): Promise<void> {
  try {
    if (list.length === 0) await SecureStore.deleteItemAsync(RECENT_KEY)
    else await SecureStore.setItemAsync(RECENT_KEY, JSON.stringify(list))
  } catch {
    // history is a convenience, never a requirement
  }
}
