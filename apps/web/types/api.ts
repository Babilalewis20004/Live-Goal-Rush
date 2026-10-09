// Kept in sync by hand with packages/shared/types.ts and the backend's
// Pydantic schemas in apps/api/app/schemas/ -- see that file for why there
// is no automated type sharing yet.

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
  articles: ArticleSummary[]
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
  | "comment.created"
  | "comment.reaction"
  | "poll.updated"
  | "match.insight.updated"
  | "prediction.updated"

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
  /** "editor" and "admin" may use the editor tools; granted by an operator. */
  role: "user" | "author" | "editor" | "admin"
  created_at: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

/** `tokens` is only populated when the request identified itself as
 * mobile (`X-Client: mobile`) -- the web client never receives raw tokens
 * in the body, relying on the httpOnly cookies set alongside this same
 * response instead. */
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
  summary?: FormSummaryOut | null
}

export interface FormSummaryOut {
  played: number
  requested: number
  wins: number
  draws: number
  losses: number
  goals_for: number
  goals_against: number
  clean_sheets: number
  failed_to_score: number
  points: number
  scoring_streak: number
  unbeaten_streak: number
  win_streak: number
  clean_sheet_streak: number
  ppg: number | null
  goals_for_per_match: number | null
  goals_against_per_match: number | null
  complete: boolean
  limitation: string | null
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
  limit: number | null
  window?: "last5" | "last10" | "all"
  period_start: string
  before: string
  meetings: HeadToHeadMeetingOut[]
  home_team_wins: number
  draws: number
  away_team_wins: number
  total_meetings?: number
  home_team_goals?: number
  away_team_goals?: number
  average_goals?: number | null
  /** The match's home team's results in these meetings, oldest to newest. */
  recent_form?: string
  complete?: boolean
  limitation?: string | null
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

// -- Discovery: news, unified search, trending, personalised feed ---------------

export interface CategoryOut {
  id: number
  slug: string
  name: string
  /** Set when the category *is* a competition ("Premier League"). */
  competition_id: number | null
}

export interface TagOut {
  id: number
  slug: string
  name: string
}

export interface ArticleSummary {
  id: number
  slug: string
  title: string
  excerpt: string
  featured_image_url: string | null
  featured_image_alt: string | null
  published_at: string | null
  category: CategoryOut | null
  /** Display name only -- never an email address. */
  author_name: string | null
  tags: TagOut[]
  /** On an entity's news list: how it relates ("match" | "team" | "competition"). */
  relation: string | null
  /** On related-article lists: why it was suggested. */
  reason: string | null
}

export interface ContentBlock {
  type: "heading" | "paragraph" | "list_item" | "quote"
  text: string
}

export interface ArticleDetail extends ArticleSummary {
  /** Sanitized HTML (server-side allow-list) -- safe to render as-is. */
  content: string
  /** The same body as blank-line separated plain-text paragraphs. */
  content_text: string
  /** The same body as typed blocks, for native rendering. */
  content_blocks: ContentBlock[]
  updated_at: string
  view_count: number
  canonical_path: string
  teams: TeamOut[]
  players: PlayerOut[]
  competitions: CompetitionOut[]
  matches: MatchSummary[]
  gallery: GalleryImage[]
}

export type ArticleStatus = "draft" | "in_review" | "scheduled" | "published" | "archived"

export interface ArticleAdminOut extends ArticleDetail {
  status: ArticleStatus
  is_featured: boolean
  author_id: number | null
  publish_at: string | null
  unpublish_at: string | null
  review_note: string | null
  featured_media_id: number | null
}

export interface ArticleAdminSummary extends ArticleSummary {
  status: ArticleStatus
  is_featured: boolean
}

export interface ArticleInput {
  title: string
  excerpt?: string
  content?: string
  featured_image_url?: string | null
  featured_image_alt?: string | null
  category_id?: number | null
  tags?: string[]
  team_ids?: number[]
  player_ids?: number[]
  competition_ids?: number[]
  match_ids?: number[]
  is_featured?: boolean
  status?: ArticleStatus
  publish_at?: string | null
  unpublish_at?: string | null
  featured_media_id?: number | null
  gallery?: { media_id: number; caption?: string }[]
}

export interface Trending<T> {
  item: T
  score: number
  /** What contributed, e.g. {views: 12, live_matches: 1} -- the ranking is explainable. */
  signals: Record<string, number>
}

export interface TrendingOut {
  window_hours: number
  teams: Trending<TeamOut>[]
  players: Trending<PlayerOut>[]
  competitions: Trending<CompetitionOut>[]
  articles: Trending<ArticleSummary>[]
}

export interface DiscoveryHome {
  latest_results: MatchSummary[]
  featured_articles: ArticleSummary[]
  latest_articles: ArticleSummary[]
  trending_teams: Trending<TeamOut>[]
  trending_players: Trending<PlayerOut>[]
  trending_articles: Trending<ArticleSummary>[]
  popular_competitions: CompetitionOut[]
  generated_at: string
}

export type FeedReason =
  | "live_followed_match"
  | "followed_team_today"
  | "followed_competition_today"
  | "followed_team_upcoming"
  | "followed_competition_upcoming"
  | "recent_result"
  | "news_followed_team"
  | "news_followed_competition"
  | "news_searched"
  | "community_match"
  | "community_article"
  | "trending"
  | "latest"

export interface FeedItem {
  kind: "match" | "article"
  reason: FeedReason
  /** Human readable, e.g. "Liverpool is playing today". */
  explanation: string
  /** 1 = most relevant tier. */
  rank: number
  match: MatchSummary | null
  article: ArticleSummary | null
}

export interface FeedOut {
  items: FeedItem[]
  /** False when the user follows nothing yet: the feed is the general one. */
  personalised: boolean
}

export interface SearchSuggestion {
  type: "team" | "player" | "competition" | "article"
  id: number
  label: string
  /** Articles are addressed by slug. */
  slug: string | null
}

export interface SearchSuggestions {
  query: string
  suggestions: SearchSuggestion[]
}

export type ContentNotificationKind =
  | "team_news"
  | "competition_news"
  | "match_reports"
  | "transfer_news"
  | "general_news"
  | "comment_replies"
  | "poll_results"
  | "editorial_updates"
  | "prediction_available"
  | "team_insights"
  | "poll_closing"
  | "subscription_events"

export interface ContentPreferenceOut {
  kind: ContentNotificationKind
  enabled: boolean
  /** What applies when the user hasn't chosen (always off). */
  default: boolean
}

export type TrackEntity = "article" | "team" | "player" | "competition" | "match"

// -- Phase 6: media, workflow, community, profiles, insights ---------------------

export interface MediaVariantOut {
  url: string
  width: number
  height: number
  size_bytes: number
}

/** Ids, dimensions and URLs only -- never a storage key or filesystem path. */
export interface MediaOut {
  id: number
  folder_id: number | null
  filename: string
  alt_text: string
  width: number
  height: number
  size_bytes: number
  created_at: string
  /** The `large` variant. */
  url: string
  thumb_url: string
  variants: Record<string, MediaVariantOut>
}

export interface FolderOut {
  id: number
  name: string
  parent_id: number | null
  media_count: number
}

export interface GalleryImage {
  media_id: number
  url: string
  thumb_url: string
  alt: string
  width: number
  height: number
  caption: string
}

export interface RevisionOut {
  version: number
  action: "create" | "update" | "status" | "restore" | "scheduled"
  /** Display name; null for system changes (scheduled publishing). */
  editor_name: string | null
  created_at: string
  changes: string[]
}

export interface FieldChange {
  field: string
  before: unknown
  after: unknown
}

export interface DiffLine {
  kind: "add" | "del" | "ctx"
  text: string
}

export interface RevisionDiff {
  article_id: number
  from_version: number
  to_version: number
  changes: FieldChange[]
  content_diff: DiffLine[]
}

export interface CommentAuthor {
  id: number
  display_name: string
  profile_public: boolean
}

export interface CommentOut {
  id: number
  author: CommentAuthor | null
  body: string
  created_at: string
  edited_at: string | null
  like_count: number
  reply_count: number
  removed: boolean
  parent_id: number | null
  liked_by_me: boolean
  mine: boolean
  replies: CommentOut[]
}

export interface CommentPage {
  items: CommentOut[]
  /** Top-level comments. */
  total: number
  /** Every visible comment including replies. */
  total_comments: number
  page: number
  page_size: number
}

export type CommentTargetType = "article" | "match"

export interface ReportOut {
  id: number
  comment_id: number
  comment_body: string
  comment_status: "visible" | "hidden" | "deleted"
  comment_author: string
  target_type: CommentTargetType
  target_id: number
  reason: string
  status: "open" | "resolved" | "dismissed"
  created_at: string
  report_count: number
}

export type ReactionKind = "thumbs_up" | "fire" | "wow" | "goal" | "heart" | "laugh" | "clap"

export interface ReactionSummary {
  counts: Record<ReactionKind, number>
  total: number
  mine: ReactionKind | null
}

export interface PollOptionOut {
  id: number
  label: string
  votes: number
  percent: number
}

export interface PollOut {
  id: number
  question: string
  kind: "match" | "transfer" | "question"
  status: "open" | "closed"
  match_id: number | null
  article_id: number | null
  closes_at: string | null
  total_votes: number
  options: PollOptionOut[]
  my_vote: number | null
  winner_option_id: number | null
}

export interface PollInput {
  question: string
  kind: "match" | "transfer" | "question"
  options: string[]
  match_id?: number | null
  article_id?: number | null
  closes_at?: string | null
}

export interface Badge {
  key: string
  label: string
  description: string
}

export interface ActivityItem {
  kind: "comment"
  text: string
  target_type: CommentTargetType
  target_id: number
  target_label: string
  target_slug: string | null
  created_at: string
}

export interface ProfileOut {
  id: number
  display_name: string
  bio: string | null
  joined: string
  badges: Badge[]
  stats: { comments: number; poll_votes: number; followed_teams: number; followed_competitions: number }
  favourite_teams: { id: number; name: string }[]
  favourite_competitions: { id: number; name: string }[]
  activity: ActivityItem[]
}

export interface MyProfileOut extends ProfileOut {
  profile_public: boolean
  role: string
}

export interface Insight {
  key: string
  text: string
  value: number | null
}

export interface InjuryOut {
  player_name: string
  photo_url: string | null
  /** "missing" = ruled out, "doubtful" = questionable. */
  kind: "missing" | "doubtful"
  reason: string | null
  /** Kickoff of the match the absence applies to. */
  match_date: string | null
}

export interface TeamInjuriesOut {
  /** False when the data provider has no injury feed. */
  supported: boolean
  items: InjuryOut[]
}

export interface TeamInsightsOut {
  team_id: number
  team_name: string
  sample_size: number
  insights: Insight[]
}

export interface MatchInsightsOut {
  match_id: number
  home: TeamInsightsOut
  away: TeamInsightsOut
  head_to_head: Insight[]
  note: string
}

// -- Phase 6b: analytics, predictions, billing -------------------------------------------------

export interface Stat {
  /** null = the provider never supplied it; never shown as 0. */
  value: number | null
  /** How many matches contributed. */
  sample: number
}

export type AnalyticsTier = "basic" | "full"

export interface RecordOut {
  played: number
  wins: number
  draws: number
  losses: number
  points: number
  points_per_match: number | null
}

export interface TeamAnalyticsOut {
  team_id: number
  team_name: string
  scope: "overall" | "home" | "away"
  window: number
  matches_considered: number
  data_timestamp: string | null
  generated_at: string
  tier: AnalyticsTier
  record: RecordOut
  attack: Record<string, Stat>
  possession: Record<string, Stat>
  defence: Record<string, Stat>
  discipline: Record<string, Stat>
  unavailable: string[]
  locked: string[]
  limitations: string[]
}

export interface PlayerMatchLine {
  match_id: number
  kickoff_time: string
  opponent: string
  minutes: number | null
  goals: number | null
  assists: number | null
  shots: number | null
  shots_on_target: number | null
  key_passes: number | null
  tackles: number | null
  yellow_cards: number | null
  red_cards: number | null
}

export interface PlayerSeasonLine {
  competition_id: number
  competition_name: string
  season: string
  appearances: number | null
  goals: number
  assists: number | null
}

export interface PlayerAnalyticsOut {
  player_id: number
  player_name: string
  generated_at: string
  tier: AnalyticsTier
  seasons: PlayerSeasonLine[]
  window: number
  matches_with_statistics: number
  totals: Record<string, Stat>
  per_90: Record<string, Stat>
  recent: PlayerMatchLine[]
  form_goal_involvements: number[]
  unavailable: string[]
  locked: string[]
  limitations: string[]
}

export interface ComparisonRow {
  key: string
  label: string
  home: number | null
  away: number | null
  /** null = neutral (e.g. possession). */
  higher_is_better: boolean | null
  home_sample: number
  away_sample: number
  premium: boolean
}

export interface MatchComparisonOut {
  match_id: number
  home_team: TeamOut
  away_team: TeamOut
  generated_at: string
  tier: AnalyticsTier
  form_window: number
  home_form: FormSummaryOut | null
  away_form: FormSummaryOut | null
  home_sequence: string
  away_sequence: string
  head_to_head: HeadToHeadOut | null
  rows: ComparisonRow[]
  locked: string[]
  limitations: string[]
}

export interface PredictionOut {
  match_id: number
  status: "available" | "insufficient_data" | "unavailable"
  label: string
  disclaimer: string
  model_version: string | null
  generated_at: string | null
  data_timestamp: string | null
  confidence: "low" | "medium" | "high" | null
  confidence_score: number | null
  home_win: number | null
  draw: number | null
  away_win: number | null
  expected_total_goals: number | null
  expected_home_goals: number | null
  expected_away_goals: number | null
  influences: string[]
  factors: Record<string, number> | null
  locked: string[]
  reason: string | null
}

export interface InsightRecordOut {
  entity_type: "team" | "player" | "match"
  entity_id: number
  insight_type: string
  text: string
  value: number | null
  source_data_version: string
  generated_at: string
}

export interface PersonalInsight {
  key: string
  text: string
  entity_type: "match" | "competition"
  entity_id: number
}

export interface PlanOut {
  code: string
  name: string
  interval: "month" | "year"
  price_minor: number
  currency: string
  entitlements: string[]
}

export interface EntitlementsOut {
  entitlements: string[]
  premium: boolean
  features: { key: string; label: string }[]
}

export interface SubscriptionOut {
  status: "none" | "incomplete" | "active" | "past_due" | "cancelled" | "expired"
  plan: string | null
  entitlements: string[]
  current_period_end: string | null
  cancel_at_period_end: boolean
}

export interface CheckoutOut {
  url: string
  session_id: string
}

export interface AdPlacementOut {
  placement: "home" | "news" | "match_centre"
  eligible: boolean
  reason: string
}

export interface PredictionEvaluationSummary {
  model_version: string
  evaluated: number
  accuracy: number | null
  mean_brier_score: number | null
  baseline_brier_score: number
  beats_baseline: boolean | null
  mean_total_goals_error: number | null
  calibration_home_win: { low: number; high: number; count: number; mean_predicted: number | null; observed_rate: number | null }[]
  note: string
}

export interface ProfileReportOut {
  id: number
  profile_user_id: number
  display_name: string
  reason: string
  status: "open" | "resolved" | "dismissed"
  created_at: string
  suspended: boolean
}
