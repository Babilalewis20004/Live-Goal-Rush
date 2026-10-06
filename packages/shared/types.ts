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
  nationality?: string | null
  shirt_number?: number | null
}

export type DataStatus = "FRESH" | "STALE" | "UNAVAILABLE"

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
  /** When this row was last written by a provider sync (Phase 2). */
  last_synced_at: string | null
  /** Computed server-side from `last_synced_at` at response time (Phase 2 §21). */
  data_status: DataStatus
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
  /** Provider-supplied qualifier (e.g. "Header"); free text, may be absent. */
  event_detail?: string | null
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
  goal_difference: number
  /** "" when the provider didn't state a season. */
  season: string
  /** Group label for group stages; "" for a single table. */
  group_name: string
  /** Provider-supplied classification (qualification, relegation...). */
  description: string | null
  /** Provider-supplied recent form, e.g. "WWDLW". */
  form: string | null
}

export interface SearchResults {
  teams: TeamOut[]
  competitions: CompetitionOut[]
  players: PlayerOut[]
  matches: MatchSummary[]
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

// -- Phase 2: WebSocket message contract (see docs/architecture/realtime.md) --

export type RealtimeEventType =
  | "MATCH_STARTED"
  | "MATCH_UPDATED"
  | "GOAL"
  | "CARD"
  | "SUBSTITUTION"
  | "HALF_TIME"
  | "SECOND_HALF_STARTED"
  | "MATCH_FINISHED"
  | "MATCH_POSTPONED"
  | "MATCH_CANCELLED"
  | "LINEUP_UPDATED"
  | "STATISTICS_UPDATED"

export interface RealtimeMatchEvent {
  id: number
  event_type: string
  minute: number
  extra_minute?: number | null
  team_id: number | null
  player: string | null
  /** Substitutions: the player going OFF (`player` is who came on). */
  assist?: string | null
  description: string | null
  event_detail?: string | null
}

/** The `match` payload of a WebSocket message -- deliberately not a full
 * `MatchSummary`: only the fields that can change in real time, keyed by
 * `id` as a string (matches `RealtimeEvent.match_id` on the backend). */
export interface RealtimeMatchPayload {
  id: string
  home_score: number
  away_score: number
  status: MatchStatus
  minute: number | null
  event?: RealtimeMatchEvent
  /** Present on STATISTICS_UPDATED. */
  statistics?: MatchStatisticsOut
}

export interface RealtimeMessage {
  type: RealtimeEventType
  match: RealtimeMatchPayload
}

// -- Phase 3: accounts, favourites, notifications --

export interface UserOut {
  id: number
  email: string
  display_name: string | null
  created_at: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

/** `tokens` is only populated when the request identified itself as
 * mobile (`X-Client: mobile`) -- the web client relies on the httpOnly
 * cookies set alongside this same response instead. */
export interface AuthResponse {
  user: UserOut
  tokens: AuthTokens | null
}

export interface FavouriteTeamOut {
  id: number
  created_at: string
  team: TeamOut
}

export interface FavouriteCompetitionOut {
  id: number
  created_at: string
  competition: CompetitionOut
}

export interface FavouriteMatchOut {
  id: number
  created_at: string
  match: MatchSummary
}

export interface FavouritesOut {
  teams: FavouriteTeamOut[]
  competitions: FavouriteCompetitionOut[]
  matches: FavouriteMatchOut[]
}

export type DevicePlatform = "expo_ios" | "expo_android" | "web"

export interface DeviceRegisterInput {
  platform: DevicePlatform
  expo_push_token?: string
  web_push_endpoint?: string
  web_push_p256dh?: string
  web_push_auth?: string
}

export interface DeviceOut {
  id: number
  platform: DevicePlatform
  last_seen_at: string | null
  created_at: string
}

export type NotificationScope = "global" | "team" | "competition" | "match"

export interface NotificationPreferenceOut {
  id: number
  scope_type: NotificationScope
  scope_id: number | null
  event_type: RealtimeEventType
  enabled: boolean
}

// -- Phase 4: match centre, teams, players, competitions --
// (mirrors apps/api/app/schemas/{lineup,statistics,form,standing,player,team,capabilities}.py)

/** What the active data provider can supply (`GET /api/v1/capabilities`).
 * `false` means "this provider never supplies it" -- distinct from "it
 * exists but hasn't been published yet" (an empty payload). */
export interface Capabilities {
  match_events: boolean
  lineups: boolean
  match_statistics: boolean
  player_statistics: boolean
  team_squads: boolean
  player_profiles: boolean
  standings: boolean
  top_scorers: boolean
  venues: boolean
  /** Can supply standings/top scorers for past seasons on request. */
  historical_seasons: boolean
  head_to_head: boolean
  form: boolean
}

export interface TeamDetail extends TeamOut {
  venue: string | null
  competitions: CompetitionOut[]
}

export interface PlayerDetail extends PlayerOut {
  team: TeamOut | null
}

export interface LineupPlayerOut {
  player: PlayerOut
  position: string | null
  shirt_number: number | null
  is_starter: boolean
  subbed_in_minute: number | null
  subbed_out_minute: number | null
}

export interface TeamLineupOut {
  team: TeamOut
  formation: string | null
  starters: LineupPlayerOut[]
  substitutes: LineupPlayerOut[]
}

/** Both null = lineups not supplied (yet, or ever -- see `Capabilities`). */
export interface MatchLineupsOut {
  home: TeamLineupOut | null
  away: TeamLineupOut | null
}

/** A `null` field = not supplied by the provider. Never render it as 0. */
export interface TeamMatchStatsOut {
  team_id: number
  possession: number | null
  shots: number | null
  shots_on_target: number | null
  corners: number | null
  fouls: number | null
  offsides: number | null
  yellow_cards: number | null
  red_cards: number | null
  pass_accuracy: number | null
  expected_goals: number | null
}

export interface MatchStatisticsOut {
  home: TeamMatchStatsOut | null
  away: TeamMatchStatsOut | null
}

export interface PlayerMatchStatsOut {
  player: PlayerOut
  team_id: number
  minutes_played: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  shots_on_target: number | null
  passes: number | null
  pass_accuracy: number | null
  key_passes: number | null
  tackles: number | null
  interceptions: number | null
  clearances: number | null
  blocks: number | null
  yellow_cards: number | null
  red_cards: number | null
  fouls_committed: number | null
}

export interface MatchPlayerStatisticsOut {
  players: PlayerMatchStatsOut[]
}

export interface PlayerSeasonStatsOut {
  competition_id: number
  competition_name: string
  season: string
  team_id: number | null
  appearances: number | null
  goals: number
  assists: number | null
  penalties: number | null
}

export interface PlayerAppearanceOut {
  match: MatchSummary
  stats: PlayerMatchStatsOut
}

export interface PlayerStatisticsOut {
  seasons: PlayerSeasonStatsOut[]
  recent_matches: PlayerAppearanceOut[]
}

export interface TeamSeasonStatsOut {
  competition_id: number
  competition_name: string
  season: string
  group: string
  position: number
  played: number
  won: number
  drawn: number
  lost: number
  goals_for: number
  goals_against: number
  goal_difference: number
  points: number
  form: string | null
}

export interface TeamStatisticsOut {
  seasons: TeamSeasonStatsOut[]
}

export interface TeamRef {
  id: number
  name: string
  short_name: string | null
  logo_url: string | null
}

export interface TopScorerOut {
  rank: number
  player: PlayerOut
  team: TeamRef | null
  goals: number
  assists: number | null
  appearances: number | null
  penalties: number | null
}

export interface TopScorersOut {
  competition_id: number
  season: string | null
  scorers: TopScorerOut[]
}

export type FormResult = "W" | "D" | "L"

export interface FormResultOut {
  match_id: number
  result: FormResult
  venue: "home" | "away"
  opponent: TeamOut
  goals_for: number
  goals_against: number
  kickoff_time: string
  competition: CompetitionOut
}

/** Historical results only -- not a prediction. `results` is most recent
 * first; `sequence` is oldest -> newest (latest on the right). */
export interface TeamFormOut {
  team_id: number
  scope: "overall" | "home" | "away"
  limit: number
  results: FormResultOut[]
  sequence: string
}

export interface MatchFormOut {
  home: TeamFormOut
  away: TeamFormOut
}

export interface HeadToHeadMeetingOut {
  match_id: number
  kickoff_time: string
  competition: CompetitionOut
  home_team: TeamOut
  away_team: TeamOut
  home_score: number
  away_score: number
}

/** Finished meetings in `period_start`..`before` (capped at `limit`),
 * wins counted relative to the match's home/away teams. */
export interface HeadToHeadOut {
  home_team_id: number
  away_team_id: number
  limit: number
  period_start: string
  before: string
  meetings: HeadToHeadMeetingOut[]
  home_team_wins: number
  draws: number
  away_team_wins: number
}

/** `GET /competitions/{id}/seasons` -- feeds the season selector. */
export interface CompetitionSeasonsOut {
  /** Latest stored season (what standings default to). */
  current: string | null
  /** Every season with stored data, newest first. */
  seasons: string[]
  /** If true, asking for a season not in `seasons` queues a background sync
   * and it shows up shortly (the immediate answer is empty). */
  historical_supported: boolean
}
