/**
 * Canonical reference for the Football Livescore API's response shapes.
 *
 * There is no automated type generation between the FastAPI backend and the
 * TypeScript clients in Phase 1 -- Python (Pydantic, apps/api/app/schemas/)
 * and TypeScript can't share types without extra tooling (e.g. openapi-typescript)
 * that isn't justified yet for a two-client MVP. Instead, this file is the
 * single hand-maintained source of truth: apps/web/types/api.ts and any
 * future apps/mobile/types/api.ts should be kept byte-for-byte identical to
 * the interfaces below, which in turn must be kept in sync with
 * apps/api/app/schemas/*.py whenever a field is added, renamed or removed.
 *
 * See docs/architecture/api-architecture.md for the full contract.
 */

export type MatchStatus =
  | "scheduled"
  | "live"
  | "halftime"
  | "finished"
  | "postponed"
  | "cancelled"

export interface CompetitionOut {
  id: number
  name: string
  country: string | null
  logo_url: string | null
  type: string
}

export interface TeamOut {
  id: number
  name: string
  short_name: string | null
  country: string | null
  logo_url: string | null
}

export interface PlayerOut {
  id: number
  name: string
  position: string | null
  photo_url: string | null
}

export interface MatchSummary {
  id: number
  competition: CompetitionOut
  home_team: TeamOut
  away_team: TeamOut
  kickoff_time: string
  status: MatchStatus
  home_score: number
  away_score: number
  half_time_home_score: number | null
  half_time_away_score: number | null
  minute: number | null
  venue: string | null
}

export interface MatchEventOut {
  id: number
  event_type: string
  minute: number
  extra_minute: number | null
  team: TeamOut | null
  player: PlayerOut | null
  assist_player: PlayerOut | null
  description: string | null
}

export interface MatchDetail extends MatchSummary {
  events: MatchEventOut[]
}

export interface StandingEntry {
  position: number
  team: TeamOut
  played: number
  won: number
  drawn: number
  lost: number
  goals_for: number
  goals_against: number
  points: number
}

export interface SearchResults {
  teams: TeamOut[]
  competitions: CompetitionOut[]
  players: PlayerOut[]
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
