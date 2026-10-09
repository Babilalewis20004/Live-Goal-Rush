import type { ConnectionStatus } from "@/lib/realtime"

/** How old live data may get, while the live connection is down, before the UI must say so. */
export const STALE_AFTER_MS = 30_000

export interface Freshness {
  /** True when what is on screen may no longer match the real scores. */
  stale: boolean
  /** One honest sentence for a banner, or null when the data can be trusted as current. */
  message: string | null
}

function clock(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
}

function ago(ms: number): string {
  const seconds = Math.max(0, Math.round(ms / 1000))
  if (seconds < 60) return "less than a minute ago"
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  return hours < 24 ? `${hours} h ago` : "over a day ago"
}

/**
 * Whether live scores can be presented as current (Phase 7 degraded mode).
 *
 * Scores are trustworthy only while something is feeding them: an open WebSocket, or a REST refresh newer than
 * `STALE_AFTER_MS`. Once the socket drops (or the app starts from a saved copy) the screen must say how old the
 * numbers are -- a frozen "2-1" that looks live is worse than an empty list.
 */
export function describeFreshness(input: {
  connection: ConnectionStatus
  lastUpdatedAt: number | null
  now: number
  fromSavedCopy?: boolean
  lastRefreshFailed?: boolean
}): Freshness {
  const { connection, lastUpdatedAt, now, fromSavedCopy = false, lastRefreshFailed = false } = input

  if (lastUpdatedAt === null) {
    return { stale: true, message: "Scores are unavailable right now." }
  }
  const age = now - lastUpdatedAt
  const when = `${clock(new Date(lastUpdatedAt))} (${ago(age)})`

  if (fromSavedCopy) {
    return { stale: true, message: `You're offline. Showing scores saved at ${when}.` }
  }
  if (connection === "open" && !lastRefreshFailed) {
    return { stale: false, message: null }
  }
  if (age <= STALE_AFTER_MS && !lastRefreshFailed) {
    return { stale: false, message: null } // a brief blip: the data is still current
  }
  if (connection === "closed") {
    return { stale: true, message: `You're offline. Scores last updated ${when}.` }
  }
  return { stale: true, message: `Reconnecting… scores last updated ${when}.` }
}
