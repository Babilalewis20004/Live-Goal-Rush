// Pure (framework-free) match-centre logic, shared in spirit between web and
// mobile: apps/mobile/src/lib/match-centre.ts is an identical copy apart from
// the `@/types/api` import path. Keeping it free of React/DOM is what lets
// vitest cover it without a component-testing setup.
//
// Nothing here knows about a football data provider: it reads the app's own
// normalized statuses/event types (see types/api.ts), never raw provider
// values.

import type {
  FormResult,
  FormResultOut,
  MatchEventOut,
  MatchStatisticsOut,
  MatchSummary,
  RealtimeMessage,
  TeamMatchStatsOut,
} from "@/types/api"

// -- match status (header) ----------------------------------------------------------

export type StatusKind = "live" | "halftime" | "finished" | "upcoming" | "postponed" | "cancelled"

export interface StatusDisplay {
  kind: StatusKind
  /** Primary label: "LIVE", "HALF TIME", "FULL TIME", "18:30", "POSTPONED"... */
  label: string
  /** Secondary line: the live minute ("67'") or, for upcoming, "Today"/"Tomorrow"/a date. */
  detail: string | null
  isLive: boolean
  /** Whether a score is meaningful yet (false before kick-off / when called off). */
  showScore: boolean
}

const DAY_MS = 24 * 60 * 60 * 1000

function utcDayNumber(d: Date): number {
  return Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / DAY_MS)
}

/** "Today" / "Tomorrow" / "Yesterday" / "Sat 04 Oct", in UTC (the app shows
 * kickoff times in UTC -- see lib/format.ts). */
export function relativeDayLabel(iso: string, now: Date = new Date()): string {
  const kickoff = new Date(iso)
  const diff = utcDayNumber(kickoff) - utcDayNumber(now)
  if (diff === 0) return "Today"
  if (diff === 1) return "Tomorrow"
  if (diff === -1) return "Yesterday"
  return kickoff.toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" })
}

function utcTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })
}

export function statusDisplay(
  match: Pick<MatchSummary, "status" | "minute" | "kickoff_time">,
  now: Date = new Date(),
): StatusDisplay {
  switch (match.status) {
    case "live":
      return {
        kind: "live",
        label: "LIVE",
        detail: match.minute != null ? `${match.minute}'` : null,
        isLive: true,
        showScore: true,
      }
    case "halftime":
      return { kind: "halftime", label: "HALF TIME", detail: null, isLive: true, showScore: true }
    case "finished":
      return { kind: "finished", label: "FULL TIME", detail: null, isLive: false, showScore: true }
    case "postponed":
      return { kind: "postponed", label: "POSTPONED", detail: null, isLive: false, showScore: false }
    case "cancelled":
      return { kind: "cancelled", label: "CANCELLED", detail: null, isLive: false, showScore: false }
    default:
      return {
        kind: "upcoming",
        label: utcTime(match.kickoff_time),
        detail: relativeDayLabel(match.kickoff_time, now),
        isLive: false,
        showScore: false,
      }
  }
}

// -- timeline ---------------------------------------------------------------------------

export type TimelineIcon =
  | "goal"
  | "own_goal"
  | "penalty"
  | "penalty_missed"
  | "yellow_card"
  | "second_yellow"
  | "red_card"
  | "substitution"
  | "var"
  | "other"

export interface TimelineItem {
  id: number
  icon: TimelineIcon
  /** "45+2'" */
  minuteLabel: string
  side: "home" | "away" | "neutral"
  /** Headline: the player (or "A → B" for a substitution). */
  title: string
  /** Secondary text: "Assist: X", a VAR decision, a provider detail... */
  subtitle: string | null
  /** Full sentence for screen readers. */
  accessibleLabel: string
  isGoal: boolean
}

export function minuteLabel(minute: number, extra: number | null | undefined): string {
  return extra ? `${minute}+${extra}'` : `${minute}'`
}

/** Chronological order with added time after the regular minute (45' before
 * 45+2' before 46'); the id breaks ties so the order is stable. */
export function sortTimeline(events: MatchEventOut[]): MatchEventOut[] {
  return [...events].sort(
    (a, b) => a.minute - b.minute || (a.extra_minute ?? 0) - (b.extra_minute ?? 0) || a.id - b.id,
  )
}

const EVENT_LABELS: Record<string, string> = {
  goal: "Goal",
  own_goal: "Own goal",
  penalty: "Penalty scored",
  penalty_missed: "Penalty missed",
  yellow_card: "Yellow card",
  second_yellow: "Second yellow card",
  red_card: "Red card",
  substitution: "Substitution",
  var: "VAR",
}

const GOAL_TYPES = new Set(["goal", "own_goal", "penalty"])

function iconFor(type: string): TimelineIcon {
  return type in EVENT_LABELS ? (type as TimelineIcon) : "other"
}

export function describeEvent(
  event: MatchEventOut,
  homeTeamId: number,
  awayTeamId: number,
): TimelineItem {
  const side = event.team?.id === homeTeamId ? "home" : event.team?.id === awayTeamId ? "away" : "neutral"
  const label = EVENT_LABELS[event.event_type] ?? "Event"
  const player = event.player?.name ?? null
  const minute = minuteLabel(event.minute, event.extra_minute)
  const teamName = event.team?.name

  let title = player ?? label
  let subtitle: string | null = null
  let spoken = `${minute} ${label}`

  if (event.event_type === "substitution") {
    // Convention (see docs/architecture/football-data.md): player = coming on,
    // assist_player = going off.
    const on = event.player?.name
    const off = event.assist_player?.name
    title = off && on ? `${off} → ${on}` : (on ?? off ?? label)
    spoken = `${minute} Substitution${teamName ? ` for ${teamName}` : ""}${on ? `: ${on} on` : ""}${off ? `, ${off} off` : ""}`
  } else if (GOAL_TYPES.has(event.event_type)) {
    subtitle = event.assist_player ? `Assist: ${event.assist_player.name}` : (event.description ?? null)
    if (event.event_type === "own_goal") subtitle = subtitle ?? "Own goal"
    spoken = `${minute} ${label}${player ? ` by ${player}` : ""}${teamName ? ` for ${teamName}` : ""}`
  } else {
    subtitle = event.event_detail ?? event.description ?? null
    spoken = `${minute} ${label}${player ? `: ${player}` : ""}${teamName ? ` (${teamName})` : ""}`
  }
  if (GOAL_TYPES.has(event.event_type) && event.event_detail && !subtitle) subtitle = event.event_detail

  return {
    id: event.id,
    icon: iconFor(event.event_type),
    minuteLabel: minute,
    side,
    title,
    subtitle,
    accessibleLabel: spoken,
    isGoal: GOAL_TYPES.has(event.event_type),
  }
}

// -- statistics -----------------------------------------------------------------------------

export type StatFormat = "count" | "percent" | "decimal"

export interface StatRow {
  key: keyof TeamMatchStatsOut
  label: string
  home: number | null
  away: number | null
  format: StatFormat
  /** Home side's share of the bar, 0..1 (0.5 when both are zero/absent). */
  homeShare: number
}

const STAT_DEFS: { key: keyof TeamMatchStatsOut; label: string; format: StatFormat }[] = [
  { key: "possession", label: "Possession", format: "percent" },
  { key: "shots", label: "Shots", format: "count" },
  { key: "shots_on_target", label: "Shots on target", format: "count" },
  { key: "corners", label: "Corners", format: "count" },
  { key: "fouls", label: "Fouls", format: "count" },
  { key: "offsides", label: "Offsides", format: "count" },
  { key: "yellow_cards", label: "Yellow cards", format: "count" },
  { key: "red_cards", label: "Red cards", format: "count" },
  { key: "pass_accuracy", label: "Pass accuracy", format: "percent" },
  { key: "expected_goals", label: "Expected goals (xG)", format: "decimal" },
]

export function barShare(home: number | null, away: number | null): number {
  const h = home ?? 0
  const a = away ?? 0
  return h + a === 0 ? 0.5 : h / (h + a)
}

/** The rows to show: only statistics the provider supplied for at least one
 * side. A statistic that is `null` for both teams is omitted entirely -- never
 * shown as 0 -- and one that is `null` for a single side keeps its row with
 * that side rendered as "–". */
export function statRows(stats: MatchStatisticsOut | null): StatRow[] {
  if (!stats || (!stats.home && !stats.away)) return []
  const rows: StatRow[] = []
  for (const def of STAT_DEFS) {
    const home = (stats.home?.[def.key] as number | null | undefined) ?? null
    const away = (stats.away?.[def.key] as number | null | undefined) ?? null
    if (home === null && away === null) continue
    rows.push({ ...def, home, away, homeShare: barShare(home, away) })
  }
  return rows
}

export function formatStat(value: number | null, format: StatFormat): string {
  if (value === null) return "–"
  if (format === "percent") return `${Math.round(value)}%`
  if (format === "decimal") return value.toFixed(2)
  return String(Math.round(value))
}

// -- form / head-to-head ----------------------------------------------------------------------

export function describeFormResult(result: FormResultOut): string {
  const word = result.result === "W" ? "Win" : result.result === "D" ? "Draw" : "Loss"
  return `${word} ${result.goals_for}-${result.goals_against} ${result.venue === "home" ? "at home" : "away"} against ${result.opponent.name}`
}

export function formSequenceLabel(sequence: string): string {
  const names: Record<FormResult, string> = { W: "win", D: "draw", L: "loss" }
  const parts = [...sequence].map((c) => names[c as FormResult] ?? c)
  return parts.length ? `Last ${parts.length} results, oldest to newest: ${parts.join(", ")}` : "No recent results"
}

// -- standings --------------------------------------------------------------------------------------

export type ZoneTone = "positive" | "europe" | "negative" | "neutral"

/** Colour bucket for a provider-supplied classification string. This only
 * *styles* whatever text the provider sent ("Champions League",
 * "Relegation"...) -- the app never decides which positions qualify or get
 * relegated. */
export function zoneTone(description: string | null): ZoneTone {
  if (!description) return "neutral"
  const d = description.toLowerCase()
  if (d.includes("relegat") || d.includes("eliminat")) return "negative"
  if (d.includes("promot") || d.includes("champions") || d.includes("knockout") || d.includes("title")) {
    return "positive"
  }
  if (d.includes("europa") || d.includes("conference") || d.includes("play") || d.includes("qualif")) {
    return "europe"
  }
  return "neutral"
}

/** Groups a standings list by `group_name`, preserving order ("" = one table). */
export function groupStandings<T extends { group_name: string }>(rows: T[]): { group: string; rows: T[] }[] {
  const groups = new Map<string, T[]>()
  for (const row of rows) {
    const list = groups.get(row.group_name) ?? []
    list.push(row)
    groups.set(row.group_name, list)
  }
  return [...groups.entries()].map(([group, list]) => ({ group, rows: list }))
}

// -- real time ------------------------------------------------------------------------------------------

/** What a WebSocket message means for the *extra* (non-score) match-centre
 * data. Score/status/minute/events are applied by `applyRealtimeMessage`;
 * these flags say which REST resources to re-fetch. One socket carries
 * everything -- no second real-time pipeline. */
export interface RefreshPlan {
  lineups: boolean
  statistics: boolean
  standings: boolean
}

export function refreshPlanFor(message: RealtimeMessage): RefreshPlan {
  switch (message.type) {
    case "LINEUP_UPDATED":
    case "SUBSTITUTION": // a substitution changes the lineup's subbed in/out minutes
      return { lineups: true, statistics: false, standings: false }
    case "MATCH_FINISHED":
      // final numbers, and the official table now includes this result
      return { lineups: true, statistics: !message.match.statistics, standings: true }
    default:
      return { lineups: false, statistics: false, standings: false }
  }
}

/** A short announcement for an `aria-live` region, or null. Only score and
 * status *changes* produce one -- the ticking minute and unrelated updates
 * do not, so screen-reader users aren't spammed on every poll. */
export function liveAnnouncement(
  prev: Pick<MatchSummary, "status" | "home_score" | "away_score">,
  next: Pick<MatchSummary, "status" | "home_score" | "away_score"> & {
    home_team: { name: string }
    away_team: { name: string }
  },
): string | null {
  const score = `${next.home_team.name} ${next.home_score}, ${next.away_team.name} ${next.away_score}`
  if (prev.status !== next.status) {
    if (next.status === "live" && prev.status === "scheduled") return `Kick-off. ${score}`
    if (next.status === "halftime") return `Half time. ${score}`
    if (next.status === "finished") return `Full time. ${score}`
    if (next.status === "postponed") return "Match postponed"
    if (next.status === "cancelled") return "Match cancelled"
  }
  if (prev.home_score !== next.home_score || prev.away_score !== next.away_score) return `Goal. ${score}`
  return null
}

/** "24 seconds ago" style text for the degraded/offline banner. */
export function formatAgo(iso: string | null, now: Date = new Date()): string | null {
  if (!iso) return null
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000))
  if (seconds < 5) return "just now"
  if (seconds < 60) return `${seconds} seconds ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`
  const hours = Math.round(minutes / 60)
  return `${hours} hour${hours === 1 ? "" : "s"} ago`
}
