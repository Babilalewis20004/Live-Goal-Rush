// Season selector logic (Phase 5). apps/mobile/src/lib/seasons.ts is an
// identical copy (a test fails if they drift). Framework-free.

import type { CompetitionSeasonsOut } from "@/types/api"

export interface SeasonOption {
  label: string
  /** Already in our database. A not-stored option is only offered when the
   * provider can supply past seasons; choosing it queues a background sync. */
  stored: boolean
}

/** "2026/27" -> "2025/26", "2026" -> "2025"; `null` for anything else. */
export function previousSeasonLabel(label: string): string | null {
  const split = /^(\d{4})\/(\d{2})$/.exec(label)
  if (split) {
    const start = Number(split[1]) - 1
    return `${start}/${String(start + 1).slice(-2)}`
  }
  if (/^\d{4}$/.test(label)) return String(Number(label) - 1)
  return null
}

/** The options for the selector: every stored season (newest first) and, if
 * the provider supports history, up to `extra` earlier seasons beyond the
 * oldest stored one. Never invents seasons the provider can't supply. */
export function selectableSeasons(info: CompetitionSeasonsOut | null, extra = 5): SeasonOption[] {
  if (!info || info.seasons.length === 0) return []
  const options: SeasonOption[] = info.seasons.map((label) => ({ label, stored: true }))
  if (!info.historical_supported) return options

  let oldest = info.seasons[info.seasons.length - 1]
  for (let i = 0; i < extra; i++) {
    const previous = previousSeasonLabel(oldest)
    if (!previous) break
    options.push({ label: previous, stored: false })
    oldest = previous
  }
  return options
}

/** How long to keep re-checking a requested past season while the background
 * sync runs: `attempts` checks, `intervalMs` apart. */
export const SEASON_POLL = { attempts: 6, intervalMs: 3_000 } as const
