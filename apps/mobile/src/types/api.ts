// Kept in sync by hand with packages/shared/types.ts, apps/web/types/api.ts,
// and the backend's Pydantic schemas in apps/api/app/schemas/ -- see
// packages/shared/types.ts for why there is no automated type sharing yet.

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

export interface RealtimeMatchEvent {
  id: number
  event_type: string
  minute: number
  team_id: number | null
  player: string | null
  description: string | null
}

export interface RealtimeMatchPayload {
  id: string
  home_score: number
  away_score: number
  status: MatchStatus
  minute: number | null
  event?: RealtimeMatchEvent
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

/** Mobile always sends `X-Client: mobile`, so `tokens` is always populated
 * here (unlike the web client, which only gets cookies). */
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
