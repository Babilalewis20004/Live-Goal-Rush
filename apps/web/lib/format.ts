import type { CompetitionOut, MatchSummary } from "@/types/api"

/** Fixed locale/timezone so server and client render identical markup
 * (kickoff times are shown in UTC in Phase 1, not the viewer's local time). */
export function formatKickoff(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
  })
}

export function formatKickoffDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
    timeZone: "UTC",
  })
}

export interface CompetitionGroup {
  competition: CompetitionOut
  matches: MatchSummary[]
}

/** Groups a flat match list by competition, preserving each competition's
 * first-seen order and each group's incoming match order. */
export function groupByCompetition(matches: MatchSummary[]): CompetitionGroup[] {
  const groups = new Map<number, CompetitionGroup>()
  for (const match of matches) {
    const existing = groups.get(match.competition.id)
    if (existing) {
      existing.matches.push(match)
    } else {
      groups.set(match.competition.id, { competition: match.competition, matches: [match] })
    }
  }
  return Array.from(groups.values())
}
